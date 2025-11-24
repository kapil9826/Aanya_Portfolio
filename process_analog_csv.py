#!/usr/bin/env python3
"""
Utility script for consolidating McCullochs analog CSV bursts into a single
per-device JSON file that contains second-by-second chart data.

The script expects up to four CSV files per device/minute (A001, A101, A201,
A301). It merges every row that starts with an analog identifier (e.g. A001)
into the `analogPerSecond` list inside the destination JSON file. Each JSON file
is keyed by `<device_serial>_<YYYY-MM-DD>.json`, so data coming from multiple
CSV files for the same device/day ends up in the same document.

Environment overrides:

    MCC_PENDING_FOLDER   Path with incoming CSV files
    MCC_COMPLETED_FOLDER Destination for processed CSV files
    MCC_JSON_FOLDER      Folder where JSON files are stored
    MCC_MAX_FILES        Optional limit (integer) of CSV files to process

All directories are created automatically when they do not exist.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

TARGET_SUFFIX_SEQUENCE = ["_A101.csv", "_A301.csv", "_A201.csv", "_A001.csv"]
CSV_SUFFIXES = tuple(TARGET_SUFFIX_SEQUENCE)

JSON_TEMPLATE = {
    "timestamps": [],
    "digitalPerSecond": [],
    "analogPerSecond": [],
    "gpsPerSecond": [],
}


@dataclass
class Config:
    pending_folder: str
    completed_folder: str
    json_folder: str
    max_files: Optional[int]
    print_json: bool


def _default_metadata_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "analog_metadata.json")


def load_analog_definitions() -> Dict[str, Dict[str, Any]]:
    metadata_path = os.environ.get("MCC_ANALOG_META", _default_metadata_path())
    if not os.path.exists(metadata_path):
        return {}
    try:
        with open(metadata_path, "r", encoding="utf-8") as meta_file:
            raw_definitions = json.load(meta_file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⚠️  Unable to read analog metadata file {metadata_path}: {exc}")
        return {}

    if isinstance(raw_definitions, list):
        candidates = {
            str(entry["id"]): entry
            for entry in raw_definitions
            if isinstance(entry, dict) and entry.get("id")
        }
    elif isinstance(raw_definitions, dict):
        candidates = {
            str(key): value
            for key, value in raw_definitions.items()
            if isinstance(value, dict)
        }
    else:
        candidates = {}

    normalized: Dict[str, Dict[str, Any]] = {}
    for analog_id, definition in candidates.items():
        entry_copy = deepcopy(definition)
        entry_copy["id"] = analog_id
        entry_copy.pop("points", None)
        normalized[analog_id] = entry_copy
    return normalized


ANALOG_DEFINITIONS = load_analog_definitions()
ANALOG_ORDER_INDEX = {analog_id: index for index, analog_id in enumerate(ANALOG_DEFINITIONS)}


def create_analog_entry(analog_id: str) -> Dict[str, Any]:
    base_entry = deepcopy(ANALOG_DEFINITIONS.get(analog_id, {}))
    base_entry.setdefault("id", analog_id)
    base_entry.setdefault("name", analog_id)
    base_entry.setdefault("unit", "")
    base_entry.setdefault("color", "#999999")
    base_entry.setdefault("min_color", base_entry["color"])
    base_entry.setdefault("max_color", base_entry["color"])
    base_entry.setdefault("resolution", 0.0)
    base_entry.setdefault("display", True)
    base_entry.setdefault("offset", "0")
    base_entry["points"] = []
    return base_entry


def new_json_document() -> Dict[str, Any]:
    document = deepcopy(JSON_TEMPLATE)
    if ANALOG_DEFINITIONS:
        document["analogPerSecond"] = [
            create_analog_entry(analog_id) for analog_id in ANALOG_DEFINITIONS
        ]
    return document


def resolve_config() -> Config:
    pending = os.environ.get(
        "MCC_PENDING_FOLDER",
        "/home/smartdatalinkcom/public_html/reet_python/mccullochs/",
    )
    completed = os.environ.get(
        "MCC_COMPLETED_FOLDER",
        "/home/smartdatalinkcom/public_html/reet_python/mccullochs/completed/",
    )
    json_folder = os.environ.get(
        "MCC_JSON_FOLDER",
        "/home/smartdatalinkcom/public_html/reet_python/mccullochs_json_files/",
    )
    max_files_env = os.environ.get("MCC_MAX_FILES")
    max_files = int(max_files_env) if max_files_env else None
    print_json = os.environ.get("MCC_PRINT_JSON", "1") != "0"

    for path in (pending, completed, json_folder):
        os.makedirs(path, exist_ok=True)

    return Config(
        pending_folder=pending,
        completed_folder=completed,
        json_folder=json_folder,
        max_files=max_files,
        print_json=print_json,
    )


def list_pending_csv_files(config: Config) -> List[str]:
    pending_files = [
        filename
        for filename in os.listdir(config.pending_folder)
        if filename.endswith(CSV_SUFFIXES)
        and os.path.isfile(os.path.join(config.pending_folder, filename))
    ]

    pending_files.sort()

    def split_base(filename: str) -> tuple[Optional[str], Optional[str]]:
        for suffix in TARGET_SUFFIX_SEQUENCE:
            if filename.endswith(suffix):
                return filename[: -len(suffix)], suffix
        return None, None

    batches: Dict[str, Dict[str, str]] = {}
    for filename in pending_files:
        base_key, suffix = split_base(filename)
        if base_key is None or suffix is None:
            continue
        batches.setdefault(base_key, {})[suffix] = filename

    for base_key in sorted(batches.keys()):
        bucket = batches[base_key]
        if all(suffix in bucket for suffix in TARGET_SUFFIX_SEQUENCE):
            ordered_files = [bucket[suffix] for suffix in TARGET_SUFFIX_SEQUENCE]
            if config.max_files is not None:
                ordered_files = ordered_files[: config.max_files]
            return ordered_files

    print("ℹ️  Waiting for the first base sequence that includes A101/A301/A201/A001 files.")
    return []


def safe_float(value: Optional[str], default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def read_csv_rows(file_path: str) -> List[List[str]]:
    with open(file_path, mode="r", encoding="utf-8", newline="") as csvfile:
        return list(csv.reader(csvfile))


def format_date(raw_date: str) -> str:
    digits = "".join(ch for ch in (raw_date or "") if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    return raw_date.strip()


def format_time(raw_time: str) -> Optional[str]:
    digits = "".join(ch for ch in (raw_time or "") if ch.isdigit())
    if len(digits) == 6:
        return f"{digits[0:2]}:{digits[2:4]}:{digits[4:6]}"
    return None


def parse_start_time(row: List[str]) -> Optional[datetime]:
    if len(row) < 2:
        return None
    formatted = format_time(row[1])
    if not formatted:
        return None
    return datetime.strptime(formatted, "%H:%M:%S")


def parse_duration(row: List[str]) -> Optional[int]:
    if len(row) < 2:
        return None
    try:
        return int(row[1])
    except (TypeError, ValueError):
        return None


def load_json(path: str) -> Dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as json_file:
                data = json.load(json_file)
                for key in JSON_TEMPLATE.keys():
                    data.setdefault(key, deepcopy(JSON_TEMPLATE[key]))
                return data
        except (json.JSONDecodeError, OSError) as exc:
            print(f"❌ Failed to read JSON {path}: {exc}. Rebuilding.")
    return new_json_document()


def save_json(path: str, data: Dict) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file, indent=4)
    os.replace(tmp_path, path)


def extract_file_type(file_name: str) -> str:
    return file_name.rsplit("_", 1)[-1].split(".", 1)[0]


def build_analog_index(analog_per_second: List[Dict]) -> Dict[str, Dict]:
    index: Dict[str, Dict] = {}
    for entry in analog_per_second:
        analog_id = entry.get("id")
        if not analog_id:
            continue
        entry_copy = deepcopy(entry)
        entry_copy["points"] = [
            {
                "time": point.get("time"),
                "avg": point.get("avg"),
                "max": point.get("max"),
                "min": point.get("min"),
            }
            for point in entry.get("points", [])
            if point.get("time")
        ]
        index[analog_id] = entry_copy
    return index


def merge_point_lists(
    existing: List[Dict[str, Optional[float]]],
    new_points: List[Dict[str, Optional[float]]],
) -> List[Dict[str, Optional[float]]]:
    point_map: Dict[str, Dict[str, Optional[float]]] = {}

    for point in existing:
        time_key = point.get("time")
        if not time_key:
            continue
        point_map[time_key] = {
            "time": time_key,
            "avg": point.get("avg"),
            "max": point.get("max"),
            "min": point.get("min"),
        }

    for point in new_points:
        time_key = point.get("time")
        if not time_key:
            continue
        merged = point_map.setdefault(
            time_key,
            {"time": time_key, "avg": None, "max": None, "min": None},
        )
        for field in ("avg", "max", "min"):
            value = point.get(field)
            if value is not None:
                merged[field] = value

    return sorted(point_map.values(), key=lambda item: item["time"])


def collect_global_timestamps(analog_index: Dict[str, Dict]) -> List[str]:
    times = set()
    for entry in analog_index.values():
        for point in entry.get("points", []):
            time_value = point.get("time")
            if time_value:
                times.add(time_value)
    return sorted(times)


def append_points(analog_index: Dict[str, Dict], analog_id: str, new_points: List[Dict]) -> None:
    if not new_points:
        return
    entry = analog_index.setdefault(analog_id, create_analog_entry(analog_id))
    entry["points"] = merge_point_lists(entry.get("points", []), new_points)


def constant_value_points(
    row: List[str],
    seconds_count: int,
    start_time: datetime,
) -> List[Dict[str, Optional[float]]]:
    if seconds_count is None or start_time is None:
        return []
    avg_value = safe_float(row[8] if len(row) > 8 else None, default=0.0)
    max_value = safe_float(row[6] if len(row) > 6 else None, default=0.0)
    min_value = safe_float(row[4] if len(row) > 4 else None, default=0.0)

    points: List[Dict[str, Optional[float]]] = []
    for offset in range(seconds_count):
        timestamp = (start_time + timedelta(seconds=offset)).strftime("%H:%M:%S")
        points.append(
            {
                "time": timestamp,
                "avg": avg_value,
                "max": max_value,
                "min": min_value,
            }
        )
    return points


def segmented_value_points(
    row: List[str],
    seconds_count: int,
    start_time: datetime,
    target_field: str,
) -> List[Dict[str, Optional[float]]]:
    if seconds_count is None or start_time is None:
        return []

    points: List[Dict[str, Optional[float]]] = []
    prev_end = -1
    idx = 1
    while idx < len(row):
        token = row[idx].strip() if row[idx] else ""
        if token == "++":
            break
        if token.startswith("T"):
            try:
                current_end = int(token[1:])
            except ValueError:
                idx += 1
                continue
            if idx + 1 >= len(row):
                break
            value = safe_float(row[idx + 1])
            if value is None:
                idx += 2
                continue
            start_second = max(prev_end + 1, 0)
            end_second = min(current_end, seconds_count - 1)
            for sec in range(start_second, end_second + 1):
                timestamp = (start_time + timedelta(seconds=sec)).strftime("%H:%M:%S")
                points.append({"time": timestamp, target_field: value})
            prev_end = current_end
            idx += 2
            continue
        idx += 1

    return points


POINT_GENERATORS = {
    "A001": lambda row, seconds, start: constant_value_points(row, seconds, start),
    "A101": lambda row, seconds, start: segmented_value_points(row, seconds, start, "avg"),
    "A201": lambda row, seconds, start: segmented_value_points(row, seconds, start, "min"),
    "A301": lambda row, seconds, start: segmented_value_points(row, seconds, start, "max"),
}


def move_to_completed(file_path: str, completed_folder: str) -> None:
    destination = os.path.join(completed_folder, os.path.basename(file_path))
    counter = 1
    target_path = destination
    while os.path.exists(target_path):
        target_path = f"{destination}.{counter}"
        counter += 1
    shutil.move(file_path, target_path)


def process_csv_file(file_name: str, config: Config) -> None:
    file_path = os.path.join(config.pending_folder, file_name)
    rows = read_csv_rows(file_path)
    if len(rows) < 4:
        print(f"⚠️  Skipping {file_name}: not enough rows.")
        move_to_completed(file_path, config.completed_folder)
        return

    header_row = rows[0]
    device_serial = header_row[2].strip() if len(header_row) > 2 else "unknown_device"
    raw_date = header_row[5].strip() if len(header_row) > 5 else datetime.utcnow().strftime("%Y%m%d")
    formatted_date = format_date(raw_date)
    json_name = f"{device_serial}_{formatted_date}.json"
    json_path = os.path.join(config.json_folder, json_name)
    current_data = load_json(json_path)
    analog_index = build_analog_index(current_data.get("analogPerSecond", []))

    start_time: Optional[datetime] = None
    seconds_count: Optional[int] = None
    file_type = extract_file_type(file_name)
    point_builder = POINT_GENERATORS.get(file_type)

    if not point_builder:
        print(f"⚠️  No parser configured for file type {file_type}; skipping {file_name}.")
        move_to_completed(file_path, config.completed_folder)
        return

    for row_number, row in enumerate(rows, start=1):
        if row_number == 2:
            start_time = parse_start_time(row)
        elif row_number == 3:
            seconds_count = parse_duration(row)
        elif row and row[0].startswith("A"):
            analog_id = row[0].strip()
            if not analog_id:
                continue
            if start_time is None or seconds_count is None:
                print(f"⚠️  Missing time metadata in {file_name}; analog rows ignored.")
                break
            new_points = point_builder(row, seconds_count, start_time)
            append_points(analog_index, analog_id, new_points)

    def sort_key(item: tuple[str, Dict[str, Any]]) -> tuple[int, str]:
        analog_id = item[0]
        return (ANALOG_ORDER_INDEX.get(analog_id, len(ANALOG_ORDER_INDEX)), analog_id)

    current_data["analogPerSecond"] = [
        deepcopy(points) for analog_id, points in sorted(analog_index.items(), key=sort_key)
    ]
    current_data["timestamps"] = collect_global_timestamps(analog_index)

    save_json(json_path, current_data)
    if config.print_json:
        print(json.dumps(current_data, indent=2))
    move_to_completed(file_path, config.completed_folder)
    print(f"✅ Processed {file_name} → {json_name}")


def main() -> None:
    config = resolve_config()
    csv_files = list_pending_csv_files(config)
    if not csv_files:
        print("ℹ️  No CSV files to process.")
        return

    print(f"📁 Found {len(csv_files)} CSV file(s) to process.")
    for file_name in csv_files:
        try:
            process_csv_file(file_name, config)
        except Exception as exc:  # pragma: no cover - safeguard for live runs
            print(f"❌ Failed to process {file_name}: {exc}")

    print("🎉 All available files have been processed.")


if __name__ == "__main__":
    main()
