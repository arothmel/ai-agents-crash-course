"""Utility for looking up nutrition facts from eurofir_mediterranean.csv."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional, TypedDict

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_PATH = REPO_ROOT / "data" / "eurofir_mediterranean.csv"
PROTEIN_THRESHOLD = 7.0
FIBER_THRESHOLD = 5.0


def _to_float(value: str | float | int) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value.strip())
    except Exception:
        return 0.0


def _match_score(query: str, candidate: str) -> int:
    if candidate == query:
        return 3
    if candidate.startswith(query):
        return 2
    if query in candidate:
        return 1
    return 0


class IngredientNutritionResult(TypedDict):
    query: str
    ingredient: str | None
    per_100g: dict[str, float]
    signals: list[str]
    source: str


class NutritionLookup:
    def __init__(self, csv_path: Path | None = None) -> None:
        self.csv_path = csv_path or DEFAULT_DATA_PATH
        self._rows = self._read_rows()

    def _read_rows(self) -> list[dict[str, str]]:
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Nutrition CSV not found: {self.csv_path}")
        with self.csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            return [row for row in reader]

    def reload(self) -> None:
        self._rows = self._read_rows()

    def lookup(self, query: str) -> Optional[IngredientNutritionResult]:
        normalized_query = query.strip().lower()
        if not normalized_query:
            return None

        best_row: dict[str, str] | None = None
        best_score = 0
        for row in self._rows:
            name = row.get("FoodName", "").strip()
            if not name:
                continue
            candidate = name.lower()
            score = _match_score(normalized_query, candidate)
            if score > best_score:
                best_score = score
                best_row = row
                if score == 3:
                    break

        if not best_row:
            return None

        per_100g = {
            "kcal": _to_float(best_row.get("ENERC_kcal", 0)),
            "protein_g": _to_float(best_row.get("PROCNT_g", 0)),
            "carbs_g": _to_float(best_row.get("CHOCDF_g", 0)),
            "fat_g": _to_float(best_row.get("FAT_g", 0)),
            "fiber_g": _to_float(best_row.get("FIB_g", 0)),
        }

        signals: list[str] = []
        if per_100g["protein_g"] >= PROTEIN_THRESHOLD:
            signals.append("protein_source")
        if per_100g["fiber_g"] >= FIBER_THRESHOLD:
            signals.append("fiber_source")

        ingredient_name = (best_row.get("FoodName", "").strip() or query).lower()

        return IngredientNutritionResult(
            query=query,
            ingredient=ingredient_name,
            per_100g=per_100g,
            signals=signals,
            source="eurofir_mediterranean",
        )


__all__ = ["NutritionLookup", "IngredientNutritionResult"]
