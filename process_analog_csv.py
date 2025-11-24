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
from typing import Dict, List, Optional

CSV_SUFFIXES = ("_A001.csv", "_A101.csv", "_A201.csv", "_A301.csv")

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

    for path in (pending, completed, json_folder):
        os.makedirs(path, exist_ok=True)

    return Config(
        pending_folder=pending,
        completed_folder=completed,
        json_folder=json_folder,
        max_files=max_files,
    )


def list_pending_csv_files(config: Config) -> List[str]:
    pending_files = [
        filename
        for filename in os.listdir(config.pending_folder)
        if filename.endswith(CSV_SUFFIXES)
        and os.path.isfile(os.path.join(config.pending_folder, filename))
    ]
    pending_files.sort()
    if config.max_files is not None:
        pending_files = pending_files[: config.max_files]
    return pending_files


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
    return deepcopy(JSON_TEMPLATE)


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
        index[analog_id] = {
            "id": analog_id,
            "points": [
                {
                    "time": point.get("time"),
                    "avg": point.get("avg"),
                    "max": point.get("max"),
                    "min": point.get("min"),
                }
                for point in entry.get("points", [])
                if point.get("time")
            ],
        }
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
    entry = analog_index.setdefault(analog_id, {"id": analog_id, "points": []})
    entry["points"] = merge_point_lists(entry["points"], new_points)


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

    current_data["analogPerSecond"] = [
        {"id": analog_id, "points": points["points"]}
        for analog_id, points in sorted(analog_index.items())
    ]
    current_data["timestamps"] = collect_global_timestamps(analog_index)

    save_json(json_path, current_data)
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
