"""Recalculate nutrition totals for an effective recipe."""

from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nutrition_lookup import NutritionLookup

MACRO_KEYS = ["kcal", "protein_g", "carbs_g", "fat_g", "fiber_g"]


@dataclass
class NutritionTotals:
    ingredient: str
    quantity: float
    unit: str | None
    per_100g: dict[str, float]
    totals: dict[str, float]


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
        breakdown: list[NutritionTotals] = []
        missing: list[str] = []

        for ingredient in ingredients:
            name = ingredient.get("name")
            if not name:
                continue
            lookup_result = self.lookup.lookup(name)
            if not lookup_result:
                missing.append(name)
                continue
            qty = self._ingredient_quantity(ingredient)
            if qty is None:
                missing.append(name)
                continue
            factor = qty / 100.0
            per_100g = lookup_result.per_100g
            contribution = {
                key: round((per_100g.get(key, 0.0) or 0.0) * factor, 6)
                for key in MACRO_KEYS
            }
            for key in MACRO_KEYS:
                totals[key] += contribution[key]
            breakdown.append(
                NutritionTotals(
                    ingredient=lookup_result.ingredient,
                    quantity=qty,
                    unit=ingredient.get("unit"),
                    per_100g=per_100g,
                    totals=contribution,
                )
            )

        per_serving = {
            key: (totals[key] / servings) if servings else totals[key]
            for key in MACRO_KEYS
        }

        return {
            "totals": totals,
            "per_serving": per_serving,
            "servings": servings,
            "breakdown": [bt.__dict__ for bt in breakdown],
            "missing": missing,
        }


__all__ = ["NutritionCalculator"]
