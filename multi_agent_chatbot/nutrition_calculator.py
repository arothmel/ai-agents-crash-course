"""Recalculate nutrition totals for an effective recipe."""

from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any, TypedDict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ingredient_normalizer import normalize_ingredient_for_lookup
from nutrition_lookup import NutritionLookup

MACRO_KEYS = ["kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"]


class RecipeBreakdownItem(TypedDict):
    ingredient: str
    matched_ingredient: str | None
    quantity: float
    unit: str | None
    per_100g: dict[str, float]
    totals: dict[str, float]


class RecipeNutritionResult(TypedDict):
    totals: dict[str, float]
    per_serving: dict[str, float]
    servings: int | float
    breakdown: list[RecipeBreakdownItem]
    missing: list[str]
    source: str


class NutritionCalculator:
    def __init__(self, lookup: NutritionLookup | None = None) -> None:
        self.lookup = lookup or NutritionLookup()

    def _ingredient_quantity(self, ingredient: dict[str, Any]) -> float | None:
        amount = ingredient.get("quantity")
        if amount is None:
            amount = ingredient.get("amount")
        try:
            return float(amount)
        except (TypeError, ValueError):
            return None

    def calculate(self, effective_recipe: dict[str, Any]) -> dict[str, Any]:
        ingredients = effective_recipe.get("ingredients", [])
        servings = effective_recipe.get("servings") or 1

        totals = {key: 0.0 for key in MACRO_KEYS}
        breakdown: list[RecipeBreakdownItem] = []
        missing: list[str] = []

        for ingredient in ingredients:
            original_name = ingredient.get("name")
            if not original_name:
                continue
            normalized = normalize_ingredient_for_lookup(ingredient)
            if normalized.skip_lookup:
                continue
            lookup_name = normalized.lookup_name
            if not lookup_name:
                missing.append(original_name)
                continue
            lookup_result = self.lookup.lookup(lookup_name)
            if not lookup_result:
                missing.append(original_name)
                continue
            qty = normalized.quantity
            if qty is None:
                qty = self._ingredient_quantity(ingredient)
            if qty is None:
                missing.append(original_name)
                continue
            factor = qty / 100.0
            per_100g = lookup_result["per_100g"]
            contribution = {
                key: round((per_100g.get(key, 0.0) or 0.0) * factor, 6)
                for key in MACRO_KEYS
            }
            for key in MACRO_KEYS:
                totals[key] += contribution[key]
            breakdown.append(
                RecipeBreakdownItem(
                    ingredient=original_name,
                    matched_ingredient=lookup_result["ingredient"],
                    quantity=qty,
                    unit=normalized.unit or ingredient.get("unit"),
                    per_100g=per_100g,
                    totals=contribution,
                )
            )

        per_serving = {
            key: (totals[key] / servings) if servings else totals[key]
            for key in MACRO_KEYS
        }

        return RecipeNutritionResult(
            totals=totals,
            per_serving=per_serving,
            servings=servings,
            breakdown=breakdown,
            missing=missing,
            source="nutrition_calculator",
        )


__all__ = [
    "NutritionCalculator",
    "RecipeNutritionResult",
    "RecipeBreakdownItem",
]
