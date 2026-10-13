"""Read-only preflight checks for generated scenario inputs.

These checks complement, rather than replace, RuFaS's InputManager validation.
"""

import calendar
import csv
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from RUFAS.scenarios_generator import load_json


def parse_date(value: str) -> datetime:
    """Parse RuFaS year:Julian-day dates without silently rolling into another year."""
    year, day = (int(part) for part in value.split(":"))
    if value != f"{year}:{day}":
        raise ValueError(f"Use year:day without leading zeros: {value}")
    if not 1 <= day <= (366 if calendar.isleap(year) else 365):
        raise ValueError(f"Invalid Julian day: {value}")
    return datetime(year, 1, 1) + timedelta(days=day - 1)


def check_metadata_files(metadata_path: Path, root: Path, seen: set[Path] | None = None) -> list[str]:
    """Check referenced data, property and runtime metadata files, including nested metadata."""
    seen = set() if seen is None else seen
    path = metadata_path.resolve()
    if path in seen:
        return []
    seen.add(path)
    if not path.is_file():
        return [f"Missing metadata: {path}"]
    metadata = load_json(path)
    errors = []
    for entry in metadata.get("files", {}).values():
        if "path" in entry and not (root / entry["path"]).is_file():
            errors.append(f"Missing input file: {entry['path']}")
    properties = metadata.get("properties", {})
    if isinstance(properties, dict):
        paths = properties.get("paths", [])
        paths = [properties["path"]] if "path" in properties else paths
        errors.extend(f"Missing properties: {p}" for p in paths if not (root / p).is_file())
    for entry in metadata.get("runtime_metadata", {}).values():
        errors.extend(check_metadata_files(root / entry["path"], root, seen))
    return errors


def check_weather(path: Path, start: datetime, end: datetime) -> list[str]:
    """Require each actual date, not merely independent year and day membership."""
    dates: set[datetime] = set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            dates.add(parse_date(f"{row['year']}:{row['jday']}"))
    missing = []
    for offset in range((end - start).days + 1):
        date = start + timedelta(days=offset)
        if date not in dates:
            missing.append(date.strftime("%Y-%m-%d"))
    return [f"Weather missing for {len(missing)} day(s), starting {missing[0]}"] if missing else []


def check_rations(feed: dict[str, Any], library_ids: set[int]) -> list[str]:
    """Check ingredient membership and finite, nonnegative percentages for every ration."""
    errors = []
    available = {item["feed_type"] for item in feed["feeds"]}
    for ration in feed["rations"]:
        label = ration["animal_combination"]
        items = ration["feeds"]
        ids = [item["feed_type"] for item in items]
        shares = [float(item["ration_percentage"]) for item in items]
        if len(ids) != len(set(ids)):
            errors.append(f"Duplicate ingredients in ration {label}")
        if set(ids) - available or set(ids) - library_ids:
            errors.append(f"Unknown or unavailable ingredients in ration {label}")
        if not shares or any(not math.isfinite(v) or v < 0 for v in shares):
            errors.append(f"Invalid percentages in ration {label}")
        elif not math.isclose(sum(shares), 100.0, abs_tol=1e-6):
            errors.append(f"Ration {label} totals {sum(shares):.2f}%, expected 100%")
    return errors


def validate_scenario(metadata_path: Path, root: Path) -> dict[str, Any]:
    """Return a structured preflight report; never repair scientific inputs silently."""
    errors: list[str] = []
    warnings = ["Preflight does not establish nutritional adequacy. RuFaS performs additional validation at runtime."]
    try:
        errors.extend(check_metadata_files(metadata_path, root))
        files = load_json(metadata_path)["files"]
        config = load_json(root / files["config"]["path"])
        animal = load_json(root / files["animal"]["path"])
        feed = load_json(root / files["feed"]["path"])
        start, end = parse_date(config["start_date"]), parse_date(config["end_date"])
        if end < start:
            errors.append("Simulation end date precedes start date")
        else:
            errors.extend(check_weather(root / files["weather"]["path"], start, end))
            if (end - start).days < 364:
                warnings.append("Less than one year of weather may affect the model's seasonal temperature fit.")
        herd = animal["herd_information"]
        fractions = list(herd["parity_fractions"].values())
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in fractions):
            errors.append("Parity fractions must be finite values between 0 and 1")
        if not math.isclose(sum(fractions), 1.0, abs_tol=1e-8):
            errors.append("Parity fractions must total 1")
        if not 0 <= herd["milking_cow_fraction"] <= 1:
            errors.append("Milking cow fraction must be between 0 and 1")
        frequency = animal["animal_config"]["management_decisions"]["cow_times_milked_per_day"]
        if not isinstance(frequency, int) or frequency < 1:
            errors.append("Milking frequency must be a positive integer")
        if not 0 <= feed["ration_formulation_parameters"]["user_defined_ration_tolerance"] <= 1:
            errors.append("Ration tolerance must be between 0 and 1")
        library_key = "NASEM_Comp" if config["nutrient_standard"] == "NASEM" else "NRC_Comp"
        with (root / files[library_key]["path"]).open(encoding="utf-8-sig", newline="") as stream:
            library_ids = {int(row["rufas_id"]) for row in csv.DictReader(stream)}
        errors.extend(check_rations(feed, library_ids))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"Could not validate input: {exc}")
    return {"valid": not errors, "errors": errors, "warnings": warnings}
