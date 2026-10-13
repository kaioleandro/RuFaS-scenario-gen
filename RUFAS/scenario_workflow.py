"""Reproducible scenario batches, readable reports and isolated RuFaS runs."""

import argparse
import csv
import hashlib
import random
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from RUFAS import scenarios_generator as generator
from RUFAS.scenario_comparison import DAY_COLUMN, METHANE_PREFIX, MILK_COLUMN, compare_runs, summarize_csv
from RUFAS.scenario_validation import check_metadata_files, parse_date, validate_scenario

GROUPS = {"rebanho", "genetica", "ordenhas", "localizacao", "alimentacao", "tolerancia"}


def selected_scenario(seed: int, vary: set[str]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Preserve unselected inputs and the original generator's random draws for each seed."""
    if vary - GROUPS:
        raise ValueError(f"Unknown variation groups: {sorted(vary - GROUPS)}")
    base_animal = generator.load_json(generator.ANIMAL_FILE)
    base_config = generator.load_json(generator.CONFIG_FILE)
    base_feed = generator.load_json(generator.FEED_FILE)
    animal, config, feed, _ = generator.generate_scenario(base_animal, base_config, base_feed, random.Random(seed))
    herd, original = animal["herd_information"], base_animal["herd_information"]
    if "rebanho" not in vary:
        for key in ["parity_fractions", "milking_cow_fraction"]:
            herd[key] = deepcopy(original[key])
    if "genetica" not in vary:
        herd["simulate_genetics"] = original["simulate_genetics"]
    if "ordenhas" not in vary:
        animal["animal_config"]["management_decisions"] = deepcopy(base_animal["animal_config"]["management_decisions"])
    if "localizacao" not in vary:
        config["FIPS_county_code"] = base_config["FIPS_county_code"]
    if "alimentacao" not in vary:
        feed["feeds"] = deepcopy(base_feed["feeds"])
        feed["rations"] = deepcopy(base_feed["rations"])
    if "tolerancia" not in vary:
        feed["ration_formulation_parameters"] = deepcopy(base_feed["ration_formulation_parameters"])
    return animal, config, feed


def describe_scenario(animal: dict[str, Any], config: dict[str, Any], feed: dict[str, Any]) -> dict[str, Any]:
    """Summarize final inputs, including values retained from the base farm."""
    herd = animal["herd_information"]
    result = {
        "start_date": config["start_date"],
        "end_date": config["end_date"],
        "FIPS_county_code": config["FIPS_county_code"],
        "cow_times_milked_per_day": animal["animal_config"]["management_decisions"]["cow_times_milked_per_day"],
        "milking_cow_fraction": herd["milking_cow_fraction"],
        "simulate_genetics": herd["simulate_genetics"],
        "user_defined_ration_tolerance": feed["ration_formulation_parameters"]["user_defined_ration_tolerance"],
    }
    result.update({f"parity_{key}": value for key, value in herd["parity_fractions"].items()})
    for ration in feed["rations"]:
        result[f"ration_{ration['animal_combination']}"] = ";".join(
            f"{item['feed_type']}:{item['ration_percentage']}" for item in ration["feeds"]
        )
    return result


def write_report(folder: Path, seed: int, vary: set[str], summary: dict[str, Any], feed: dict[str, Any]) -> None:
    """Use feed names from the input library, retaining IDs for traceability."""
    with generator.FEED_EXTRATION_FILE.open(encoding="utf-8-sig", newline="") as stream:
        names = {int(row["rufas_id"]): row["Name"] for row in csv.DictReader(stream)}
    lines = [
        f"# Cenário {seed}",
        "",
        f"Grupos sorteados: {', '.join(sorted(vary)) or 'nenhum'}.",
        "Os demais valores foram preservados da fazenda base.",
        "",
        f"- Período: {summary['start_date']} a {summary['end_date']} (ano:dia do ano)",
        f"- Ordenhas por dia: {summary['cow_times_milked_per_day']}",
        f"- Vacas em lactação: {summary['milking_cow_fraction']:.2%}",
        f"- Genética simulada: {summary['simulate_genetics']}",
        f"- Condado FIPS: {summary['FIPS_county_code']}",
        "- O sorteio do FIPS não troca o arquivo climático nem os demais dados regionais.",
        f"- Tolerância da ração: {summary['user_defined_ration_tolerance']}",
        "",
        "## Distribuição de partos",
        "",
    ]
    lines.extend(f"- Paridade {key[7:]}: {value:.0%}" for key, value in summary.items() if key.startswith("parity_"))
    for ration in feed["rations"]:
        lines.extend(
            [
                "",
                f"## Ração: {ration['animal_combination']}",
                "",
                "| ID | Alimento (nome da biblioteca) | % da matéria seca |",
                "|---|---|---|",
            ]
        )
        for item in ration["feeds"]:
            feed_id = item["feed_type"]
            name = names.get(feed_id, "Nome não disponível").replace("|", "/")
            lines.append(f"| {feed_id} | {name} | {item['ration_percentage']:.2f} |")
    lines.extend(["", "As regras de composição não comprovam adequação nutricional."])
    (folder / "resumo.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_inputs(folder: Path, seed: int, data: tuple[dict[str, Any], ...]) -> None:
    """Write metadata and tasks without mutating the generator's global paths."""
    metadata = generator.load_json(generator.METADATA_FILE)
    for kind, content in zip(["animal", "config", "feed"], data):
        path = folder / f"example_{kind}_random.json"
        generator.save_json(content, path)
        metadata["files"][kind]["path"] = path.relative_to(generator.ROOT).as_posix()
    generator.save_json(metadata, folder / "scenario_metadata.json")
    tasks = generator.load_json(generator.TASK_FILE)
    tasks["parallel_workers"] = 1
    for task in tasks["tasks"]:
        task["metadata_file_path"] = (folder / "scenario_metadata.json").relative_to(generator.ROOT).as_posix()
        task["output_prefix"] = f"seed{seed}"
    generator.save_json(tasks, folder / "scenario_task.json")
    manager = generator.load_json(generator.ROOT / "input/task_manager_metadata.json")
    manager["files"]["tasks"]["path"] = (folder / "scenario_task.json").relative_to(generator.ROOT).as_posix()
    generator.save_json(manager, folder / "scenario_task_manager_metadata.json")


def generate_batch(seed: int, count: int, vary: set[str], destination: Path, days: int | None = None) -> list[Path]:
    """Generate consecutive seeds; reject all collisions before writing any scenario."""
    if count < 1 or (days is not None and days < 1):
        raise ValueError("Quantity and duration must be positive")
    destination = destination.resolve()
    if not destination.is_relative_to((generator.ROOT / "scenarios").resolve()):
        raise ValueError("Scenario destination must be inside the repository's scenarios/ directory")
    folders = [destination / f"seed{value}" for value in range(seed, seed + count)]
    if days is not None:
        folders = [folder / f"teste_{days}_dias" for folder in folders]
    manifest_path = destination / f"batch_seed{seed}_n{count}_days{days or 'full'}.json"
    summary_path = manifest_path.with_suffix(".csv")
    existing = [path for path in [*folders, manifest_path, summary_path] if path.exists()]
    if existing:
        raise FileExistsError(f"Destination already exists: {existing[0]}. Choose another --saida or seed.")
    errors = check_metadata_files(generator.METADATA_FILE, generator.ROOT)
    if errors:
        raise ValueError("\n".join(errors))
    generator.validate_ration_profiles(generator.load_feed_library_ids(generator.FEED_EXTRATION_FILE))
    records = []
    for scenario_seed, folder in zip(range(seed, seed + count), folders):
        animal, config, feed = selected_scenario(scenario_seed, vary)
        if days is not None:
            end = parse_date(config["start_date"]) + timedelta(days=days - 1)
            config["end_date"] = f"{end.year}:{end.timetuple().tm_yday}"
        folder.mkdir(parents=True, exist_ok=False)
        write_inputs(folder, scenario_seed, (animal, config, feed))
        summary = describe_scenario(animal, config, feed)
        record = {"seed": scenario_seed, "varied_groups": ",".join(sorted(vary)), **summary}
        validation = validate_scenario(folder / "scenario_metadata.json", generator.ROOT)
        generator.save_json(validation, folder / "validation.json")
        generator.save_json(record, folder / "scenario.json")
        write_report(folder, scenario_seed, vary, summary, feed)
        record["valid"] = validation["valid"]
        record["folder"] = folder.relative_to(generator.ROOT).as_posix()
        records.append(record)
    generator.save_json({"schema_version": 1, "scenarios": records}, manifest_path)
    with summary_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    invalid = [record["seed"] for record in records if not record["valid"]]
    if invalid:
        raise ValueError(f"Preflight failed for seeds {invalid}. See validation.json; no simulation was started.")
    return folders


def prepare_run(folder: Path, simulation_seed: int) -> tuple[Path, dict[str, Any]]:
    """Make a unique run directory and snapshot the generated JSON inputs."""
    validation = validate_scenario(folder / "scenario_metadata.json", generator.ROOT)
    generator.save_json(validation, folder / "validation.json")
    if not validation["valid"]:
        raise ValueError("Preflight failed: " + "; ".join(validation["errors"]))
    if not 1 <= simulation_seed <= 2**32 - 1:
        raise ValueError("Simulation seed must be in 1..4294967295 (zero asks RuFaS for a random seed)")
    metadata = generator.load_json(folder / "scenario_metadata.json")
    config = generator.load_json(generator.ROOT / metadata["files"]["config"]["path"])
    tasks = generator.load_json(folder / "scenario_task.json")
    if len(tasks["tasks"]) != 1 or tasks["tasks"][0]["task_type"] != "SIMULATION_SINGLE_RUN":
        raise ValueError("This workflow requires exactly one SIMULATION_SINGLE_RUN task")
    task = tasks["tasks"][0]
    for path in task.get("cross_validation_file_paths", []):
        if not (generator.ROOT / path).is_file():
            raise FileNotFoundError(f"Missing cross-validation file: {path}")
    scenario_seed = int(task["output_prefix"].removeprefix("seed"))
    days = (parse_date(config["end_date"]) - parse_date(config["start_date"])).days + 1
    if days < 30:
        raise ValueError("Use at least 30 days for this workflow; very short seasonal fits can be unstable")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    run_dir = generator.ROOT / "output" / folder.relative_to(generator.ROOT) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    inputs = run_dir / "inputs"
    inputs.mkdir()
    for kind in ["animal", "config", "feed"]:
        source = generator.ROOT / metadata["files"][kind]["path"]
        target = inputs / f"example_{kind}_random.json"
        target.write_bytes(source.read_bytes())
        metadata["files"][kind]["path"] = target.relative_to(generator.ROOT).as_posix()
    generator.save_json(metadata, inputs / "scenario_metadata.json")
    task.update(
        {
            "random_seed": simulation_seed,
            "suppress_log_files": False,
            "variable_name_style": "verbose",
            "chunkification": False,
        }
    )
    task["metadata_file_path"] = (inputs / "scenario_metadata.json").relative_to(generator.ROOT).as_posix()
    for key, subdir in {
        "csv_output_directory": "CSVs",
        "json_output_directory": "JSONs",
        "logs_directory": "logs",
        "graphics_directory": "graphics",
        "report_directory": "reports",
        "filters_directory": "filters",
    }.items():
        task[key] = (run_dir / subdir).relative_to(generator.ROOT).as_posix()
    filters = run_dir / "filters"
    filters.mkdir()
    (filters / "csv_scenario_metrics.txt").write_text(
        "\n".join([MILK_COLUMN.rsplit(" (", 1)[0], DAY_COLUMN.rsplit(" (", 1)[0], METHANE_PREFIX + ".*"]) + "\n",
        encoding="utf-8",
    )
    generator.save_json(tasks, run_dir / "tasks.json")
    manager = generator.load_json(folder / "scenario_task_manager_metadata.json")
    manager["files"]["tasks"]["path"] = (run_dir / "tasks.json").relative_to(generator.ROOT).as_posix()
    generator.save_json(manager, run_dir / "task_manager_metadata.json")
    manifest = {
        "schema_version": 1,
        "status": "running",
        "scenario_seed": scenario_seed,
        "simulation_seed": simulation_seed,
        "start_date": config["start_date"],
        "end_date": config["end_date"],
        "simulation_type": config["simulation_type"],
        "days": days,
        "scenario_folder": str(folder.relative_to(generator.ROOT)),
        "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.glob("*.json")},
    }
    generator.save_json(manifest, run_dir / "run.json")
    return run_dir, manifest


def simulate_scenario(folder: Path, simulation_seed: int = 42) -> Path:
    """Fail on task errors even if RuFaS's parent process returns exit code zero."""
    run_dir, manifest = prepare_run(folder, simulation_seed)
    run_file = run_dir / "run.json"
    try:
        with (run_dir / "console.log").open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(generator.ROOT / "main.py"),
                    "-p",
                    str(run_dir / "task_manager_metadata.json"),
                    "--no-graphics",
                    "-o",
                    str(run_dir),
                    "-l",
                    str(run_dir / "logs"),
                ],
                cwd=generator.ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if completed.returncode:
            raise RuntimeError(f"RuFaS exited with code {completed.returncode}; see {run_dir / 'console.log'}")
        error_files = list((run_dir / "logs").glob("*errors*.json"))
        if not error_files:
            raise RuntimeError("RuFaS did not produce error logs; run completion could not be verified")
        for path in error_files:
            errors = generator.load_json(path)
            if any(key != "DISCLAIMER" for key in errors):
                raise RuntimeError(f"RuFaS reported errors: {path}")
        csv_files = list((run_dir / "CSVs").glob("*csv_scenario_metrics*.csv"))
        if len(csv_files) != 1:
            raise RuntimeError("Expected exactly one metrics CSV for this run")
        manifest["metrics"] = summarize_csv(csv_files[0], manifest["days"])
        manifest["csv_path"] = csv_files[0].relative_to(run_dir).as_posix()
        manifest["status"] = "completed"
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        raise
    finally:
        generator.save_json(manifest, run_file)
    return run_file


def main(argv: list[str] | None = None) -> None:
    """CLI preserving the local --seed/--dias/--simular commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=43, help="Primeira semente do cenário")
    parser.add_argument("--quantidade", type=int, default=1)
    parser.add_argument("--variar", nargs="+", choices=sorted(GROUPS | {"todos", "nenhum"}), default=["todos"])
    parser.add_argument("--dias", type=int)
    parser.add_argument("--saida", type=Path, default=Path("scenarios"))
    parser.add_argument("--simular", action="store_true")
    parser.add_argument("--seed-simulacao", type=int, default=42)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--validar", type=Path, help="Validar uma pasta de cenário existente")
    modes.add_argument("--executar", type=Path, help="Simular um cenário existente, sem regenerar")
    modes.add_argument("--comparar", nargs="+", type=Path, help="Arquivos run.json de execuções concluídas")
    parser.add_argument("--comparacao-saida", type=Path, default=Path("output/comparison"))
    args = parser.parse_args(argv)
    try:
        if args.comparar:
            compare_runs([resolve_path(path) for path in args.comparar], resolve_path(args.comparacao_saida))
            print(f"Comparação salva em: {resolve_path(args.comparacao_saida)}")
        elif args.validar:
            report = validate_scenario(resolve_path(args.validar) / "scenario_metadata.json", generator.ROOT)
            for category in ["warnings", "errors"]:
                for message in report[category]:
                    print(f"{category}: {message}")
            if not report["valid"]:
                raise ValueError("Preflight failed")
            print("Validação preliminar OK")
        elif args.executar:
            print(f"Execução concluída: {simulate_scenario(resolve_path(args.executar), args.seed_simulacao)}")
        else:
            run_batch_command(args)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        parser.exit(1, f"Erro: {exc}\n")


def resolve_path(path: Path) -> Path:
    """Resolve CLI paths from the repository root, independently of the working directory."""
    return (generator.ROOT / path).resolve()


def run_batch_command(args: argparse.Namespace) -> None:
    """Generate, optionally execute, then compare a successfully completed batch."""
    if len(args.variar) > 1 and ({"todos", "nenhum"} & set(args.variar)):
        raise ValueError("Use 'todos' ou 'nenhum' sozinho")
    if args.simular and (args.dias is not None and args.dias < 30):
        raise ValueError("Use pelo menos 30 dias para simular neste fluxo")
    if args.simular and not 1 <= args.seed_simulacao <= 2**32 - 1:
        raise ValueError("Seed da simulação deve estar entre 1 e 4294967295")
    vary = GROUPS if args.variar == ["todos"] else set() if args.variar == ["nenhum"] else set(args.variar)
    folders = generate_batch(args.seed, args.quantidade, vary, resolve_path(args.saida), args.dias)
    runs = []
    for index, folder in enumerate(folders, 1):
        print(f"[{index}/{len(folders)}] Cenário: {folder}; resumo.md e validation.json disponíveis", flush=True)
        if args.simular:
            print("Simulando; os detalhes serão salvos em console.log...", flush=True)
            runs.append(simulate_scenario(folder, args.seed_simulacao))
            print(f"Execução concluída: {runs[-1]}", flush=True)
    if len(runs) > 1:
        target = generator.ROOT / "output" / "comparisons" / uuid4().hex[:12]
        compare_runs(runs, target)
        print(f"Comparação: {target}")


if __name__ == "__main__":
    main()
