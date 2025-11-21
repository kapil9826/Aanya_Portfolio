import csv
import json
import os
import shutil
import time
from datetime import datetime, timedelta

import pymysql

print("Python working")

# -------------------------
# Folder paths
# -------------------------
pending_folder = "/home/smartdatalinkcom/public_html/reet_python/mccullochs/"
completed_folder = "/home/smartdatalinkcom/public_html/reet_python/mccullochs/completed/"
json_folder = "/home/smartdatalinkcom/public_html/reet_python/mccullochs_json_files/"

# csv_files1 = [f for f in os.listdir(pending_folder) if f.endswith(("_100.csv", "_200.csv", "_300.csv"))]
# print(len(csv_files1))
# print("\n")


# -------------------------
# Get CSV files
# -------------------------
csv_files = [f for f in os.listdir(pending_folder) if f.endswith(("_A001.csv", "_A101.csv", "_A201.csv"))]
csv_files = csv_files[:1]  # process only first file for now


# -------------------------
# DB Connection
# -------------------------
conn = pymysql.connect(
    host="localhost",
    user="smartdatalinkcom_sdl",
    password="D)uqkU7?YQrKV-%F",
    database="smartdatalinkcom_sdl",
)
cursor = conn.cursor()
print("✅ Connected successfully!")


# -------------------------
# Function: Get JSON file data
# -------------------------
def get_json_file_data(file_name):
    json_file_path = os.path.join(json_folder, file_name)
    if os.path.exists(json_file_path):
        try:
            with open(json_file_path, "r", encoding="utf-8") as f:
                json_file_data = json.load(f)
                return json_file_data
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error in {file_name}: {e}")
            return None
    else:
        # Create a new JSON skeleton
        data_template = {
            "timestamps": [],
            "digitalPerSecond": [],
            "analogPerSecond": [],
            "gpsPerSecond": [],
        }
        with open(json_file_path, "w", encoding="utf-8") as f:
            json.dump(data_template, f, indent=4)
        return None


# -------------------------
# Function: GPS latitude and longitude convert krne k liye
# -------------------------
def convert_dmm_to_decimal(value, direction):
    """
    Convert coordinates from DMM (Degrees + Decimal Minutes)
    to Decimal Degrees (DD)
    Example: 3754.56246,S -> -37.909374
    """
    if not value or value.strip() == "":
        return None

    # split into degrees and minutes
    degrees = int(float(value) // 100)
    minutes = float(value) - (degrees * 100)
    decimal = degrees + (minutes / 60)

    # apply direction
    if direction in ["S", "W"]:
        decimal = -decimal

    return round(decimal, 6)


# -------------------------
# Loop through CSV files
# -------------------------
for f1 in csv_files:
    # csv file read krne k liye folder and file name
    file_path = os.path.join(pending_folder, f1)
    print(f"\n📂 Checking file: {f1}")

    with open(file_path, mode="r", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        analog_rows = list(reader)
        row_number = 1

        formatted_date = None
        start_datetime = None
        duration_seconds = None
        max_samples = None
        analog_blocks = []
        current_block = []

        for analog_row in analog_rows:
            if not analog_row:
                row_number += 1
                continue

            if row_number == 1:
                company_name = analog_row[0]
                device_serial_no = analog_row[2]
                file_date = analog_row[5]
                formatted_date = f"{file_date[0:4]}-{file_date[4:6]}-{file_date[6:8]}"
                file_name = f"{device_serial_no}_{formatted_date}.json"
                current_data = get_json_file_data(file_name)
                file_path = os.path.join(json_folder, file_name)
                print(formatted_date)
                print("\n-----------------------\n")

            elif row_number == 2:
                file_time = analog_row[1]
                formatted_time = f"{file_time[:2]}:{file_time[2:4]}:{file_time[4:]}"
                if formatted_date:
                    start_datetime = datetime.strptime(f"{formatted_date} {formatted_time}", "%Y-%m-%d %H:%M:%S")
                print(formatted_time)
                print("\n-----------------------\n")

            elif row_number == 3:
                duration_value = analog_row[1] if len(analog_row) > 1 else "0"
                try:
                    duration_seconds = int(duration_value)
                    max_samples = duration_seconds + 1  # include the starting second
                except ValueError:
                    duration_seconds = None
                    max_samples = None

                duration_output = f"Duration - {duration_value}"
                if start_datetime and duration_seconds is not None:
                    end_time = start_datetime + timedelta(seconds=duration_seconds)
                    duration_output += f" (until {end_time.strftime('%H:%M:%S')})"

                print(duration_output)
                print("\n-----------------------\n")

            elif analog_row[0][:1] == "A":
                analog_id = analog_row[0]

                if analog_id == "A001" and current_block:
                    analog_blocks.append(current_block)
                    current_block = []

                current_block.append(analog_row)

            row_number = row_number + 1

        if current_block:
            analog_blocks.append(current_block)

        if not analog_blocks:
            print("⚠️ No analog data blocks found.")
            continue

        seconds_to_emit = max_samples if max_samples is not None else len(analog_blocks)

        for second_index in range(seconds_to_emit):
            timestamp = (
                start_datetime + timedelta(seconds=second_index)
                if start_datetime is not None
                else None
            )
            timestamp_label = timestamp.strftime("%H:%M:%S") if timestamp else f"Second {second_index}"

            if second_index < len(analog_blocks):
                block = analog_blocks[second_index]
            else:
                block = analog_blocks[-1]

            for analog_row in block:
                print(f"{timestamp_label} -> {analog_row}")

print("\n✅ Processing completed!")
