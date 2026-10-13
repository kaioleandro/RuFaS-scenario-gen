"""Behavioral tests for scenario generation, validation and result comparison."""

import csv
import random
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

import pytest

from RUFAS import scenario_workflow as workflow
from RUFAS import scenarios_generator as generator
from RUFAS.scenario_comparison import DAY_COLUMN, METHANE_PREFIX, MILK_COLUMN, compare_runs, summarize_csv
from RUFAS.scenario_validation import check_rations, check_weather, parse_date, validate_scenario


def test_all_groups_preserve_original_seed_behavior() -> None:
    bases = tuple(
        generator.load_json(path) for path in [generator.ANIMAL_FILE, generator.CONFIG_FILE, generator.FEED_FILE]
    )
    expected = generator.generate_scenario(bases[0], bases[1], bases[2], random.Random(44))[:3]
    assert workflow.selected_scenario(44, workflow.GROUPS) == expected
    assert workflow.selected_scenario(44, workflow.GROUPS) == workflow.selected_scenario(44, workflow.GROUPS)


def test_no_groups_preserves_entire_base() -> None:
    expected = tuple(
        generator.load_json(path) for path in [generator.ANIMAL_FILE, generator.CONFIG_FILE, generator.FEED_FILE]
    )
    assert workflow.selected_scenario(44, set()) == expected


def test_feed_only_keeps_herd_management_location_and_tolerance() -> None:
    animal, config, feed = workflow.selected_scenario(44, {"alimentacao"})
    assert animal == generator.load_json(generator.ANIMAL_FILE)
    assert config == generator.load_json(generator.CONFIG_FILE)
    base_feed = generator.load_json(generator.FEED_FILE)
    assert feed["ration_formulation_parameters"] == base_feed["ration_formulation_parameters"]
    assert feed["rations"] != base_feed["rations"]
    assert feed == workflow.selected_scenario(44, workflow.GROUPS - {"tolerancia"})[2]


@pytest.fixture
def batch_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate generated artifacts while retaining the real base farm data."""
    manager = generator.load_json(generator.ROOT / "input/task_manager_metadata.json")
    (tmp_path / "input").mkdir()
    generator.save_json(manager, tmp_path / "input/task_manager_metadata.json")
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    monkeypatch.setattr(workflow, "check_metadata_files", lambda *_: [])
    monkeypatch.setattr(workflow, "validate_scenario", lambda *_: {"valid": True, "errors": [], "warnings": []})
    return tmp_path / "scenarios"


def test_batch_unique_seeds_reports_and_no_global_mutation(batch_root: Path) -> None:
    old_seed, old_dir = generator.SEED, generator.OUTPUT_DIR
    paths = workflow.generate_batch(70, 3, {"alimentacao"}, batch_root, 30)
    assert [generator.load_json(path / "scenario.json")["seed"] for path in paths] == [70, 71, 72]
    assert generator.load_json(paths[0] / "example_config_random.json")["end_date"] == "2013:30"
    assert "Alimento" in (paths[0] / "resumo.md").read_text(encoding="utf-8")
    assert "Nome não disponível" not in (paths[0] / "resumo.md").read_text(encoding="utf-8")
    assert len(list(csv.DictReader(next(batch_root.glob("batch*.csv")).open(encoding="utf-8")))) == 3
    assert (generator.SEED, generator.OUTPUT_DIR) == (old_seed, old_dir)


def test_batch_collision_does_not_write_earlier_seeds(batch_root: Path) -> None:
    (batch_root / "seed71").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        workflow.generate_batch(70, 3, workflow.GROUPS, batch_root)
    assert not (batch_root / "seed70").exists()


@pytest.mark.parametrize("count,days", [(0, 30), (-1, 30), (1, 0), (1, -5)])
def test_invalid_batch_arguments(batch_root: Path, count: int, days: int) -> None:
    with pytest.raises(ValueError):
        workflow.generate_batch(70, count, workflow.GROUPS, batch_root, days)
    assert not batch_root.exists()


@pytest.mark.parametrize("value", ["2013:366", "2012:367", "2013:0", "2013:003", "abc"])
def test_invalid_dates(value: str) -> None:
    with pytest.raises(ValueError):
        parse_date(value)


def test_leap_date() -> None:
    assert parse_date("2012:366") == datetime(2012, 12, 31)


def test_weather_checks_date_pairs(tmp_path: Path) -> None:
    weather = tmp_path / "weather.csv"
    weather.write_text("year,jday\n2012,1\n2013,2\n", encoding="utf-8")
    assert check_weather(weather, datetime(2013, 1, 1), datetime(2013, 1, 2))


@pytest.mark.parametrize("shares", [[50, 40], [-10, 110], [float("nan"), 100]])
def test_invalid_ration_percentages(shares: list[float]) -> None:
    feed = {
        "feeds": [{"feed_type": 1}, {"feed_type": 2}],
        "rations": [
            {
                "animal_combination": "lac_cow",
                "feeds": [
                    {"feed_type": 1, "ration_percentage": shares[0]},
                    {"feed_type": 2, "ration_percentage": shares[1]},
                ],
            },
        ],
    }
    assert check_rations(feed, {1, 2})


def test_real_base_passes_preflight() -> None:
    report = validate_scenario(generator.METADATA_FILE, generator.ROOT)
    assert report["valid"], report["errors"]


def test_missing_metadata_reports_error(tmp_path: Path) -> None:
    assert not validate_scenario(tmp_path / "missing.json", tmp_path)["valid"]


def metrics_csv(path: Path, rows: list[list[Any]] | None = None) -> Path:
    """Two pens, two days: 30 kg milk and 1 kg enteric methane total."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([DAY_COLUMN, MILK_COLUMN, METHANE_PREFIX + "pen1 (g)", METHANE_PREFIX + "pen2 (g)"])
        writer.writerows(rows if rows is not None else [[0, 10, 100, 200], [1, 20, 300, 400]])
    return path


def test_comparison_aggregates_and_converts_grams(tmp_path: Path) -> None:
    result = summarize_csv(metrics_csv(tmp_path / "metrics.csv"), 2)
    assert result["milk_total_kg"] == 30
    assert result["milk_daily_mean_kg"] == 15
    assert result["enteric_methane_total_kg"] == 1
    assert result["enteric_methane_kg_per_kg_milk"] == pytest.approx(1 / 30)


@pytest.mark.parametrize(
    "rows",
    [
        [[0, 10, 100, 200]],
        [[0, 10, 100, 200], [0, 20, 300, 400]],
        [[0, "", 100, 200], [1, 20, 300, 400]],
        [[0, "NaN", 100, 200], [1, 20, 300, 400]],
        [[0, 10, 100, ""], [1, 20, 300, 400]],
    ],
)
def test_comparison_rejects_incomplete_results(tmp_path: Path, rows: list[list[Any]]) -> None:
    with pytest.raises(ValueError):
        summarize_csv(metrics_csv(tmp_path / "metrics.csv", rows), 2)


def test_zero_milk_has_no_infinite_intensity(tmp_path: Path) -> None:
    result = summarize_csv(metrics_csv(tmp_path / "metrics.csv", [[0, 0, 100, 200]]), 1)
    assert "enteric_methane_kg_per_kg_milk" not in result


def test_compare_runs_rejects_failed_and_different_periods(tmp_path: Path) -> None:
    csv_path = metrics_csv(tmp_path / "metrics.csv")
    run = {
        "status": "completed",
        "scenario_seed": 1,
        "simulation_seed": 42,
        "days": 2,
        "start_date": "2013:1",
        "end_date": "2013:2",
        "simulation_type": "full_farm",
        "csv_path": csv_path.name,
    }
    first, second = tmp_path / "one.json", tmp_path / "two.json"
    generator.save_json(run, first)
    run["status"] = "failed"
    generator.save_json(run, second)
    with pytest.raises(ValueError, match="not complete"):
        compare_runs([first, second], tmp_path / "comparison")
    run.update(status="completed", start_date="2014:1", end_date="2014:2")
    generator.save_json(run, second)
    with pytest.raises(ValueError, match="same start/end"):
        compare_runs([first, second], tmp_path / "comparison")
    assert not (tmp_path / "comparison").exists()
    run.update(start_date="2013:1", end_date="2013:2")
    generator.save_json(run, second)
    assert len(compare_runs([first, second], tmp_path / "comparison")) == 2
    assert (tmp_path / "comparison/comparison.md").is_file()


def test_runtime_error_despite_zero_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = {"status": "running", "days": 2}
    monkeypatch.setattr(workflow, "prepare_run", lambda *_: (tmp_path, deepcopy(run)))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: CompletedProcess([], 0))
    (tmp_path / "logs").mkdir()
    generator.save_json({"TaskManager.failure": {}}, tmp_path / "logs/task_errors.json")
    with pytest.raises(RuntimeError, match="reported errors"):
        workflow.simulate_scenario(tmp_path)
    assert generator.load_json(tmp_path / "run.json")["status"] == "failed"


def test_success_requires_complete_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "prepare_run", lambda *_: (tmp_path, {"status": "running", "days": 2}))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: CompletedProcess([], 0))
    (tmp_path / "logs").mkdir()
    (tmp_path / "CSVs").mkdir()
    generator.save_json({"DISCLAIMER": "example"}, tmp_path / "logs/task_errors.json")
    metrics_csv(tmp_path / "CSVs/csv_scenario_metrics.csv")
    run_file = workflow.simulate_scenario(tmp_path)
    assert generator.load_json(run_file)["status"] == "completed"


def test_comparison_rejects_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "metrics.csv"
    path.write_text("other\n12\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Missing"):
        summarize_csv(path, 1)


def test_comparison_ignores_only_fully_empty_padding(tmp_path: Path) -> None:
    path = metrics_csv(tmp_path / "metrics.csv", [[0, 10, 100, 200], [1, 20, 300, 400], ["", "", "", ""]])
    assert summarize_csv(path, 2)["milk_total_kg"] == 30


def test_preflight_rejects_modified_config(tmp_path: Path) -> None:
    metadata = generator.load_json(generator.METADATA_FILE)
    config = generator.load_json(generator.CONFIG_FILE)
    config["end_date"] = "2012:1"
    generator.save_json(config, tmp_path / "config.json")
    metadata["files"]["config"]["path"] = str(tmp_path / "config.json")
    generator.save_json(metadata, tmp_path / "metadata.json")
    report = validate_scenario(tmp_path / "metadata.json", generator.ROOT)
    assert not report["valid"]
    assert "Simulation end date precedes start date" in report["errors"]


def test_batch_size_does_not_change_first_scenario(batch_root: Path) -> None:
    one = workflow.generate_batch(80, 1, workflow.GROUPS, batch_root / "one")[0]
    many = workflow.generate_batch(80, 2, workflow.GROUPS, batch_root / "many")[0]
    for kind in ["animal", "config", "feed"]:
        assert (one / f"example_{kind}_random.json").read_bytes() == (many / f"example_{kind}_random.json").read_bytes()


def test_unknown_variation_group_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown"):
        workflow.selected_scenario(44, {"typo"})


def test_existing_comparison_is_not_overwritten(tmp_path: Path) -> None:
    csv_path = metrics_csv(tmp_path / "metrics.csv")
    run = {
        "status": "completed",
        "scenario_seed": 1,
        "simulation_seed": 42,
        "days": 2,
        "start_date": "2013:1",
        "end_date": "2013:2",
        "simulation_type": "full_farm",
        "csv_path": csv_path.name,
    }
    files = [tmp_path / "one.json", tmp_path / "two.json"]
    for path in files:
        generator.save_json(run, path)
    destination = tmp_path / "comparison"
    destination.mkdir()
    sentinel = destination / "comparison.csv"
    sentinel.write_text("existing results", encoding="utf-8")
    with pytest.raises(FileExistsError):
        compare_runs(files, destination)
    assert sentinel.read_text(encoding="utf-8") == "existing results"
