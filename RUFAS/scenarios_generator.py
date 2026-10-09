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

OUTPUT_DIR  = ROOT / "scenarios"
SEED = 43

MILKING_OPTIONS = [2, 3]
GENETICS_OPTIONS = [False, True]
TOLERANCE_RANGE = (0.05, 0.15)
RATION_VARIATION = 0.15
RATION_ANIMAL_COMBINATION = "LAC_COW" 

def main() -> None:
    base_animal = load_json(ANIMAL_FILE)
    base_config = load_json(CONFIG_FILE)
    base_feed = load_json(FEED_FILE)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_rows = []

    scenario_seed = SEED 
    rng = random.Random(scenario_seed) 

    animal, config, feed, summary = generate_scenario( base_animal, base_config, base_feed, rng)

    save_json(animal, OUTPUT_DIR / "example_animal_random.json")
    save_json(config, OUTPUT_DIR / "example_config_random.json")
    save_json(feed,   OUTPUT_DIR / "example_feed_random.json")

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
    herd["milking_cow_fraction"] = randomize_milking_fraction(rng)
    herd["simulate_genetics"] = rng.choice(GENETICS_OPTIONS)

    management = animal["animal_config"]["management_decisions"]
    management["cow_times_milked_per_day"] = rng.choice(MILKING_OPTIONS)

    config["FIPS_county_code"] = rng.choice(load_fips(FIPS_EXTRATION_FILE))

    params = feed["ration_formulation_parameters"]
    params["user_defined_ration_tolerance"] = round(rng.uniform(*TOLERANCE_RANGE), 3)

    lac_cow = find_ration(feed, RATION_ANIMAL_COMBINATION)
    lac_cow["feeds"] = randomize_lac_cow_ration(lac_cow["feeds"], rng)

    summary = {
        "cow_times_milked_per_day": management["cow_times_milked_per_day"],
        "FIPS_county_code": config["FIPS_county_code"],
        "milking_cow_fraction": herd["milking_cow_fraction"],
        "simulate_genetics": herd["simulate_genetics"],
        "user_defined_ration_tolerance": params["user_defined_ration_tolerance"],
    }
    for parity, value in herd["parity_fractions"].items():
        summary[f"parity_{parity}"] = value
    for item in lac_cow["feeds"]:
        summary[f"lac_cow_feed_{item['feed_type']}"] = item["ration_percentage"]

    return animal, config, feed, summary

def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)

def save_json(data: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

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


def randomize_milking_fraction(rng: random.Random) -> float:
    return round(rng.uniform(0.407, 1.0), 4)


def randomize_lac_cow_ration(feeds: list[dict], rng: random.Random) -> list[dict]:
    original_total = sum(f["ration_percentage"] for f in feeds)
    values = [
        f["ration_percentage"] * (1 + rng.uniform(-RATION_VARIATION, RATION_VARIATION))
        for f in feeds
    ]
    new_values = normalize(values, total=original_total, decimals=2)

    new_feeds = deepcopy(feeds)
    for feed, value in zip(new_feeds, new_values):
        feed["ration_percentage"] = value
    return new_feeds


def find_ration(feed_config: dict, animal_combination: str) -> dict:
    for ration in feed_config["rations"]:
        if ration["animal_combination"].lower() == animal_combination.lower():
            return ration
    raise KeyError(f"Ração '{animal_combination}' não encontrada no arquivo de feed.")

if __name__ == "__main__":
    main()