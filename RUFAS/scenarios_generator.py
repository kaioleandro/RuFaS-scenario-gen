import csv
import json
import random
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   

ANIMAL_FILE = ROOT / "input/data/animal/example_freestall_animal.json"
CONFIG_FILE = ROOT / "input/data/config/example_freestall_config.json"
FEED_FILE   = ROOT / "input/data/feed/example_Midwest_feed.json"

FIPS_EXTRATION_FILE   = ROOT / "input/data/EEE/full_feeds_emissions_July2024_interpolated_regional_average.csv"
FEED_EXTRATION_FILE   = ROOT / "input/data/feed/NASEM_Comp_with_TDN_urea.csv"


METADATA_FILE = ROOT / "input/metadata/example_freestall_dairy_metadata.json"
TASK_FILE     = ROOT / "input/data/tasks/example_freestall_task.json"

OUTPUT_DIR  = ROOT / "scenarios"
SEED = 44

MILKING_OPTIONS = [2, 3]
MILKING_FRACTION_VARIATION = 0.05
MILKING_FRACTION_BOUNDS = (0.50, 1.00)
GENETICS_OPTIONS = [False, True]
TOLERANCE_RANGE = (0.05, 0.15)


MIN_FEED_SHARE = 1.0                  # % mínima da MS para qualquer feed incluído
FORAGE_DIRICHLET_ALPHAS = (3.0, 1.5)  # (forragem principal, demais): a 1ª tende a dominar
CONCENTRATE_DIRICHLET_ALPHA = 2.0
FORAGE_COST = 0.01
PURCHASED_FEED_DEFAULTS = {
    "buffer": 0.15,
    "runtime_purchase_allowance": 1000.0,
    "advance_purchase_allowance": 1000000.0,
    "planning_cycle_allowance": 1000.0,
}


FORAGE_FAMILIES = {
    "corn_silage": [50, 51, 52],
    "legume_silage": [109, 110],
    "grass_legume_silage": [97, 100, 104],
    "grass_silage": [91],
    "small_grain_silage": [12, 187, 198],
    "legume_hay": [102, 103, 106, 107, 108],
    "grass_hay": [88, 89, 94, 95, 99],
}

RATION_PROFILES = {
    "lac_cow": {
        "forage_share": (40.0, 60.0),
        "forage_count_weights": {1: 1, 2: 4, 3: 4, 4: 2},
        "forage_family_weights": {
            "corn_silage": 6, "legume_silage": 4, "grass_legume_silage": 2, "legume_hay": 2,
            "grass_silage": 1, "grass_hay": 1, "small_grain_silage": 1,
        },
        "concentrates": [
            {"name": "energy", "share": (12.0, 25.0), "count": (1, 2), "probability": 1.0,
             "absolute": False, "cost": 0.5, "candidates": [8, 40, 43, 44, 46, 47, 194]},
            {"name": "protein", "share": (10.0, 22.0), "count": (1, 2), "probability": 1.0,
             "absolute": False, "cost": 0.1,
             "candidates": [24, 25, 31, 36, 42, 60, 164, 167, 170, 302, 303, 304, 305]},
            {"name": "byproduct", "share": (3.0, 10.0), "count": (1, 1), "probability": 0.5,
             "absolute": False, "cost": 0.1, "candidates": [2, 4, 15, 33, 49, 58, 163, 197]},
            {"name": "fat", "share": (0.5, 2.5), "count": (1, 1), "probability": 0.3,
             "absolute": True, "cost": 0.1, "candidates": [67, 79]},
            {"name": "mineral", "share": (1.5, 4.0), "count": (1, 1), "probability": 1.0,
             "absolute": True, "cost": 1.0, "candidates": [301]},
        ],
    },
}

def main() -> None:
    base_animal = load_json(ANIMAL_FILE)
    base_config = load_json(CONFIG_FILE)
    base_feed = load_json(FEED_FILE)
    validate_ration_profiles(load_feed_library_ids(FEED_EXTRATION_FILE))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_rows = []

    scenario_seed = SEED 
    rng = random.Random(scenario_seed) 

    animal, config, feed, summary = generate_scenario( base_animal, base_config, base_feed, rng)

    save_json(animal, OUTPUT_DIR / "example_animal_random.json")
    save_json(config, OUTPUT_DIR / "example_config_random.json")
    save_json(feed,   OUTPUT_DIR / "example_feed_random.json")
    write_run_files(scenario_seed)

    csv_rows.append({
        "seed": scenario_seed,
        **summary,
    })

    csv_file = OUTPUT_DIR / "scenarios.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)

def generate_scenario(base_animal: dict, base_config: dict, base_feed: dict, rng: random.Random):
    animal = deepcopy(base_animal)
    config = deepcopy(base_config)
    feed = deepcopy(base_feed)

    herd = animal["herd_information"]
    herd["parity_fractions"] = randomize_parity_fractions(herd["parity_fractions"], rng)
    herd["milking_cow_fraction"] = randomize_milking_fraction(herd["milking_cow_fraction"], rng)
    herd["simulate_genetics"] = rng.choice(GENETICS_OPTIONS)

    management = animal["animal_config"]["management_decisions"]
    management["cow_times_milked_per_day"] = rng.choice(MILKING_OPTIONS)

    config["FIPS_county_code"] = rng.choice(load_fips(FIPS_EXTRATION_FILE))

    params = feed["ration_formulation_parameters"]
    params["user_defined_ration_tolerance"] = round(rng.uniform(*TOLERANCE_RANGE), 3)

    ration_summary = {}
    for combination, profile in RATION_PROFILES.items():
        ration = find_ration(feed, combination)
        ration["feeds"], costs, forage_share = compose_ration(profile, rng)
        add_purchased_feeds(feed, costs)

        ration_summary[f"{combination}_forage_share"] = forage_share
        ration_summary[f"{combination}_ration"] = ";".join(
            f"{item['feed_type']}:{item['ration_percentage']}" for item in ration["feeds"]
        )

    summary = {
        "cow_times_milked_per_day": management["cow_times_milked_per_day"],
        "FIPS_county_code": config["FIPS_county_code"],
        "milking_cow_fraction": herd["milking_cow_fraction"],
        "simulate_genetics": herd["simulate_genetics"],
        "user_defined_ration_tolerance": params["user_defined_ration_tolerance"],
    }
    for parity, value in herd["parity_fractions"].items():
        summary[f"parity_{parity}"] = value
    summary.update(ration_summary)

    return animal, config, feed, summary

def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)

def save_json(data: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

def write_run_files(seed: int) -> None:
    """
    Gera o metadata e o task file do cenário. Os caminhos são relativos à raiz
    do repositório, que é de onde o RuFaS deve ser executado.
    """
    metadata = load_json(METADATA_FILE)
    files = metadata["files"]
    files["config"]["path"] = (OUTPUT_DIR / "example_config_random.json").relative_to(ROOT).as_posix()
    files["animal"]["path"] = (OUTPUT_DIR / "example_animal_random.json").relative_to(ROOT).as_posix()
    files["feed"]["path"]   = (OUTPUT_DIR / "example_feed_random.json").relative_to(ROOT).as_posix()
    metadata_path = OUTPUT_DIR / "scenario_metadata.json"
    save_json(metadata, metadata_path)

    task_config = load_json(TASK_FILE)
    for task in task_config["tasks"]:
        task["metadata_file_path"] = metadata_path.relative_to(ROOT).as_posix()
        task["output_prefix"] = f"seed{seed}"
    task_path = OUTPUT_DIR / "scenario_task.json"
    save_json(task_config, task_path)

    task_manager = load_json(ROOT / "input/task_manager_metadata.json")
    task_manager["files"]["tasks"]["path"] = task_path.relative_to(ROOT).as_posix()
    save_json(task_manager, OUTPUT_DIR / "scenario_task_manager_metadata.json")


def load_fips(filepath):
    with open(filepath, "r", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        return [
            int(row["county_code"])
            for row in reader
            if row["county_code"]
        ]


def normalize(values: list[float], total: float, decimals: int) -> list[float]:
    scale = total / sum(values)
    scaled = [round(v * scale, decimals) for v in values]
    diff = round(total - sum(scaled), decimals)
    scaled[scaled.index(max(scaled))] = round(max(scaled) + diff, decimals)
    return scaled

def randomize_parity_fractions(original: dict, rng: random.Random) -> dict:
    values = {
        key: rng.random() if rng.random() > 0.1 else 0.0
        for key in original
    }

    total = sum(values.values())

    if total == 0:
        key = rng.choice(list(original.keys()))
        values[key] = 1.0
        total = 1.0

    result = {
        key: round(value / total, 2)
        for key, value in values.items()
    }

    key = max(result, key=result.get)
    result[key] = round(result[key] + 1.0 - sum(result.values()), 2)

    return result


def randomize_milking_fraction(original: float, rng: random.Random) -> float:
    value = original * (1 + rng.uniform(-MILKING_FRACTION_VARIATION, MILKING_FRACTION_VARIATION))
    low, high = MILKING_FRACTION_BOUNDS
    return round(min(max(value, low), high), 4)


def load_feed_library_ids(filepath: Path) -> set[int]:
    with open(filepath, "r", encoding="utf-8") as file:
        return {int(row["rufas_id"]) for row in csv.DictReader(file)}


def validate_ration_profiles(library_ids: set[int]) -> None:
    """Garante que os IDs existem na biblioteca e não se repetem dentro de um perfil."""
    for combination, profile in RATION_PROFILES.items():
        ids = [i for family in profile["forage_family_weights"] for i in FORAGE_FAMILIES[family]]
        ids += [i for slot in profile["concentrates"] for i in slot["candidates"]]

        missing = sorted(set(ids) - library_ids)
        if missing:
            raise ValueError(f"Perfil '{combination}' usa feeds fora da biblioteca: {missing}")
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        if repeated:
            raise ValueError(f"Perfil '{combination}' repete feeds entre famílias/slots: {repeated}")


def weighted_sample(weights: dict, k: int, rng: random.Random) -> list:
    """Sorteia `k` chaves distintas de `weights`, com probabilidade proporcional ao peso."""
    pool = dict(weights)
    chosen = []
    for _ in range(min(k, len(pool))):
        key = rng.choices(list(pool), weights=list(pool.values()))[0]
        chosen.append(key)
        del pool[key]
    return chosen


def split_share(total: float, alphas: list[float], rng: random.Random) -> list[float]:
    """
    Divide `total` em len(alphas) partes via Dirichlet, garantindo um piso de
    MIN_FEED_SHARE para cada parte (ou metade da divisão igual, se não couber).
    """
    floor = min(MIN_FEED_SHARE, total / (2 * len(alphas)))
    weights = [rng.gammavariate(alpha, 1.0) for alpha in alphas]
    free = total - floor * len(alphas)
    return [floor + free * w / sum(weights) for w in weights]


def compose_ration(profile: dict, rng: random.Random) -> tuple[list[dict], dict[int, float], float]:
    """
    Monta uma ração a partir de um perfil de RATION_PROFILES.

    Retorna a lista de feeds no formato do RuFaS (somando exatamente 100),
    o custo de compra padrão de cada feed escolhido e a fração de volumoso.
    """
    counts = profile["forage_count_weights"]
    n_forages = rng.choices(list(counts), weights=list(counts.values()))[0]
    families = weighted_sample(profile["forage_family_weights"], n_forages, rng)
    forage_ids = [rng.choice(FORAGE_FAMILIES[family]) for family in families]
    forage_share = rng.uniform(*profile["forage_share"])

    absolute, relative = [], []
    for slot in profile["concentrates"]:
        if rng.random() >= slot["probability"]:
            continue
        k = min(rng.randint(*slot["count"]), len(slot["candidates"]))
        picked = (rng.sample(slot["candidates"], k), rng.uniform(*slot["share"]), slot["cost"])
        (absolute if slot["absolute"] else relative).append(picked)

    remainder = 100.0 - forage_share - sum(share for _, share, _ in absolute)
    if relative:
        scale = remainder / sum(share for _, share, _ in relative)
        relative = [(ids, share * scale, cost) for ids, share, cost in relative]
    else:
        forage_share += remainder

    forage_alphas = [FORAGE_DIRICHLET_ALPHAS[0]] + [FORAGE_DIRICHLET_ALPHAS[1]] * (len(forage_ids) - 1)
    groups = [(forage_ids, forage_share, FORAGE_COST, forage_alphas)]
    groups += [(ids, share, cost, [CONCENTRATE_DIRICHLET_ALPHA] * len(ids)) for ids, share, cost in absolute + relative]

    feed_ids, values, costs = [], [], {}
    for ids, share, cost, alphas in groups:
        for feed_id, value in zip(ids, split_share(share, alphas, rng)):
            feed_ids.append(feed_id)
            values.append(value)
            costs[feed_id] = cost

    values = normalize(values, total=100.0, decimals=2)
    feeds = [{"feed_type": i, "ration_percentage": v} for i, v in sorted(zip(feed_ids, values))]
    return feeds, costs, round(forage_share, 2)


def add_purchased_feeds(feed_config: dict, costs: dict[int, float]) -> None:
    """
    O RuFaS exige que todo feed de uma ração esteja na lista `feeds` de topo.
    Adiciona os que faltam (com custo padrão do slot) e mantém os existentes.
    """
    existing = {item["feed_type"] for item in feed_config["feeds"]}
    for feed_id, cost in costs.items():
        if feed_id not in existing:
            feed_config["feeds"].append(
                {"feed_type": feed_id, "purchased_feed_cost": cost, **PURCHASED_FEED_DEFAULTS}
            )
    feed_config["feeds"].sort(key=lambda item: item["feed_type"])


def find_ration(feed_config: dict, animal_combination: str) -> dict:
    for ration in feed_config["rations"]:
        if ration["animal_combination"].lower() == animal_combination.lower():
            return ration
    raise KeyError(f"Ração '{animal_combination}' não encontrada no arquivo de feed.")

if __name__ == "__main__":
    main()