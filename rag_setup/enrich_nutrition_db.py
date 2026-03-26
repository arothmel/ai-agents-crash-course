"""Upsert Mediterranean EuroFIR foods into the nutrition_db Chroma collection."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import chromadb


def load_eurofir(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [row for row in reader]


def build_document(row: dict[str, str]) -> tuple[str, dict[str, float | str]]:
    kcal = float(row.get("ENERC_kcal", 0) or 0)
    kj = round(kcal * 4.184, 1)
    protein = float(row.get("PROCNT_g", 0) or 0)
    fat = float(row.get("FAT_g", 0) or 0)
    carbs = float(row.get("CHOCDF_g", 0) or 0)
    fiber = float(row.get("FIB_g", 0) or 0)

    document = (
        f"Food: {row['FoodName']}\n"
        f"Category: {row['FoodGroup']}\n"
        f"Nutrient snapshot per 100g:\n"
        f"- Calories: {kcal:g} kcal ({kj:g} kJ)\n"
        f"- Protein: {protein:g} g\n"
        f"- Fat: {fat:g} g\n"
        f"- Carbohydrates: {carbs:g} g\n"
        f"- Fiber: {fiber:g} g\n"
        f"Notes: {row.get('Notes', '').strip()}"
    )

    metadata = {
        "food_item": row["FoodName"].lower(),
        "food_category": row["FoodGroup"].lower(),
        "calories_per_100g": kcal,
        "kj_per_100g": kj,
        "protein_g": protein,
        "fat_g": fat,
        "carbs_g": carbs,
        "fiber_g": fiber,
        "serving_info": "100g",
        "source": row.get("Source", "EuroFIR"),
        "notes": row.get("Notes", ""),
        "keywords": f"{row['FoodName'].lower().replace(' ', '_')}_{row['FoodGroup'].lower().replace(' ', '_')}",
        "origin": "mediterranean_eurofir",
    }
    return document, metadata


def upsert_rows(csv_path: Path, chroma_path: Path, collection_name: str) -> int:
    rows = load_eurofir(csv_path)
    docs: list[str] = []
    metadatas: list[dict[str, float | str]] = []
    ids: list[str] = []

    for row in rows:
        document, metadata = build_document(row)
        docs.append(document)
        metadatas.append(metadata)
        ids.append(f"med_{row['FoodID'].lower()}")

    chroma_path = chroma_path.expanduser().resolve()
    chroma_path.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(str(chroma_path))
    collection = client.get_or_create_collection(collection_name)
    collection.upsert(documents=docs, metadatas=metadatas, ids=ids)
    return len(docs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich nutrition_db with EuroFIR foods")
    parser.add_argument(
        "--csv",
        default=Path("data/eurofir_mediterranean.csv"),
        type=Path,
        help="EuroFIR CSV to ingest",
    )
    parser.add_argument(
        "--collection",
        default="nutrition_db",
        help="Chroma collection name",
    )
    parser.add_argument(
        "--chroma-path",
        default=Path("chroma_mediterranean"),
        type=Path,
        help="Path to Chroma persistent directory",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    count = upsert_rows(args.csv, args.chroma_path, args.collection)
    print(f"Upserted {count} Mediterranean foods into collection '{args.collection}'.")


if __name__ == "__main__":
    main()
