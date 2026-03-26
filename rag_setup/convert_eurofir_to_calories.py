"""Convert a EuroFIR-style nutrient table into the course's calories.csv format."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

CAL_HEADER = [
    "FoodCategory",
    "FoodItem",
    "per100grams",
    "Cals_per100grams",
    "KJ_per100grams",
]


def load_eurofir_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [row for row in reader]


def eurofir_group_to_category(group: str) -> str:
    group = group.strip() or "Misc"
    mapping = {
        "Mediterranean base": "Mediterranean base",
        "Protein sources": "Protein",
        "Carbs": "Carbohydrates",
        "Extras": "Extras",
    }
    return mapping.get(group, group)


def to_calorie_row(row: dict[str, str]) -> dict[str, str]:
    kcal = float(row.get("ENERC_kcal", 0) or 0)
    kj = round(kcal * 4.184, 1)
    return {
        "FoodCategory": eurofir_group_to_category(row.get("FoodGroup", "")),
        "FoodItem": row.get("FoodName", "").strip(),
        "per100grams": "100g",
        "Cals_per100grams": f"{kcal:g} cal",
        "KJ_per100grams": f"{kj:g} kJ",
    }


def convert(eurofir_path: Path, output_path: Path) -> int:
    rows = load_eurofir_rows(eurofir_path)
    calorie_rows = [to_calorie_row(row) for row in rows]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CAL_HEADER)
        writer.writeheader()
        writer.writerows(calorie_rows)
    return len(calorie_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert EuroFIR nutrient table into the calories.csv format"
    )
    parser.add_argument(
        "--input",
        default=Path("data/eurofir_mediterranean.csv"),
        type=Path,
        help="Path to the EuroFIR CSV table",
    )
    parser.add_argument(
        "--output",
        default=Path("data/calories_mediterranean.csv"),
        type=Path,
        help="Destination calories-format CSV",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    count = convert(args.input, args.output)
    print(f"Wrote {count} rows to {args.output}")


if __name__ == "__main__":
    main()
