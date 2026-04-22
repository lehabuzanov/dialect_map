from __future__ import annotations

import csv
from pathlib import Path

from data_loader import EXPECTED_MAP_FIELDS, load_csv_rows


ROOT = Path(__file__).resolve().parent.parent
SOURCE_CSV = ROOT / "data" / "csv" / "dialect_map_data.csv"
TARGET_CSV = ROOT / "data" / "csv" / "dialect_map_data_answers_v2.csv"


def main() -> None:
    rows = load_csv_rows(SOURCE_CSV, EXPECTED_MAP_FIELDS)
    with TARGET_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPECTED_MAP_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"written={len(rows)} file={TARGET_CSV}")


if __name__ == "__main__":
    main()
