"""Compare complete daily milk and enteric methane series with explicit units."""

import csv
import math
from pathlib import Path
from typing import Any

from RUFAS.scenarios_generator import load_json
from RUFAS.scenario_validation import parse_date

MILK_COLUMN = "AnimalModuleReporter.report_herd_statistics_data.daily_milk_production (kg/day)"
DAY_COLUMN = "AnimalModuleReporter.report_herd_statistics_data.simulation_day (day)"
METHANE_PREFIX = "AnimalModuleReporter.report_enteric_methane_emission.enteric_methane_emission_for_"


def summarize_csv(path: Path, expected_days: int) -> dict[str, float | int]:
    """Reject missing, nonfinite or incomplete data rather than interpreting it as zero."""
    if expected_days < 1:
        raise ValueError("Expected days must be positive")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        methane = [name for name in headers if name.startswith(METHANE_PREFIX) and name.endswith(" (g)")]
        if MILK_COLUMN not in headers or DAY_COLUMN not in headers or not methane:
            raise ValueError(f"Missing daily milk, day or enteric methane columns: {path}")
        if len(headers) != len(set(headers)):
            raise ValueError(f"Duplicate CSV columns: {path}")
        series: dict[str, list[float]] = {name: [] for name in [MILK_COLUMN, DAY_COLUMN, *methane]}
        for row in reader:
            values = [row.get(name) for name in series]
            if all(value == "" for value in values):
                continue  # RuFaS pads wide CSVs for longer, nondaily variables.
            if any(value is None or value == "" for value in values):
                raise ValueError(f"Incomplete daily row in {path}")
            for name in series:
                value = float(row[name])
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"Invalid numeric value for {name}: {row[name]}")
                series[name].append(value)
    if series[DAY_COLUMN] != list(range(expected_days)):
        raise ValueError(f"Expected consecutive simulation days 0..{expected_days - 1} in {path}")
    return _aggregate_series(series, methane, expected_days)


def _aggregate_series(series: dict[str, list[float]], methane: list[str], expected_days: int) -> dict[str, float | int]:
    """Aggregate complete daily series and convert methane grams to kilograms."""
    milk_kg = sum(series[MILK_COLUMN])
    methane_kg = sum(sum(series[name]) for name in methane) / 1000.0
    result: dict[str, float | int] = {
        "days": expected_days,
        "milk_total_kg": milk_kg,
        "milk_daily_mean_kg": milk_kg / expected_days,
        "enteric_methane_total_kg": methane_kg,
        "enteric_methane_daily_mean_kg": methane_kg / expected_days,
    }
    if milk_kg > 0:
        result["enteric_methane_kg_per_kg_milk"] = methane_kg / milk_kg
    return result


def compare_runs(run_files: list[Path], destination: Path) -> list[dict[str, Any]]:
    """Compare successful run manifests from the same date window and simulation type."""
    if len(run_files) < 2:
        raise ValueError("Select at least two run.json files to compare")
    if len({path.resolve() for path in run_files}) != len(run_files):
        raise ValueError("The same run was selected more than once")
    rows: list[dict[str, Any]] = []
    periods = set()
    for path in run_files:
        run = load_json(path)
        if run["status"] != "completed":
            raise ValueError(f"Run is not complete: {path}")
        duration = (parse_date(run["end_date"]) - parse_date(run["start_date"])).days + 1
        if run["days"] != duration:
            raise ValueError(f"Run duration does not match its date window: {path}")
        periods.add((run["start_date"], run["end_date"], run["simulation_type"]))
        metrics = summarize_csv(path.parent / run["csv_path"], run["days"])
        rows.append(
            {
                "run": str(path.resolve()),
                "scenario_seed": run["scenario_seed"],
                "simulation_seed": run["simulation_seed"],
                "start_date": run["start_date"],
                "end_date": run["end_date"],
                **metrics,
            }
        )
    if len(periods) != 1:
        raise ValueError("Runs must have the same start/end dates and simulation type")
    destination.mkdir(parents=True, exist_ok=False)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with (destination / "comparison.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Comparação de simulações",
        "",
        "Metano entérico de todos os lotes de animais reportados; não representa as emissões totais da fazenda.",
        "Mesma janela de datas. Diferenças não estabelecem causalidade nem significância estatística.",
        "",
        "| Seed do cenário | Seed da simulação | Dias | Leite total (kg) | Metano entérico total (kg) |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['scenario_seed']} | {row['simulation_seed']} | {row['days']} | "
            f"{row['milk_total_kg']:.3f} | {row['enteric_methane_total_kg']:.3f} |"
        )
    lines.extend(["", "## Arquivos de origem", "", *(f"- {path.resolve()}" for path in run_files)])
    (destination / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows
