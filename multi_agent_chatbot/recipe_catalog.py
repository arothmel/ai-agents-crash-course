"""In-memory catalog of canonical recipes for demo purposes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

DEFAULT_RECIPE_ID = "recipe_101"

_RECIPE_CATALOG: Dict[str, Dict[str, Any]] = {
    "recipe_101": {
        "id": "recipe_101",
        "title": "Mediterranean Chickpea Bowl",
        "servings": 4,
        "ingredients": [
            {"name": "chickpeas", "quantity": 150, "unit": "g"},
            {"name": "arugula", "quantity": 40, "unit": "g"},
            {"name": "olive oil", "quantity": 15, "unit": "ml"},
            {"name": "feta cheese", "quantity": 30, "unit": "g"},
            {"name": "lemon juice", "quantity": 15, "unit": "ml"},
        ],
    },
    "recipe_102": {
        "id": "recipe_102",
        "title": "Heritage Grain Salad",
        "servings": 2,
        "ingredients": [
            {"name": "quinoa cooked", "quantity": 200, "unit": "g"},
            {"name": "spinach", "quantity": 60, "unit": "g"},
            {"name": "tomatoes", "quantity": 80, "unit": "g"},
            {"name": "olive oil", "quantity": 10, "unit": "ml"},
            {"name": "almonds", "quantity": 20, "unit": "g"},
        ],
    },
}


def get_recipe(recipe_id: str | None) -> Dict[str, Any]:
    recipe = _RECIPE_CATALOG.get(recipe_id or DEFAULT_RECIPE_ID)
    if not recipe:
        raise KeyError(f"Unknown recipe id: {recipe_id}")
    return deepcopy(recipe)


def list_recipes() -> list[dict[str, Any]]:
    return [deepcopy(recipe) for recipe in _RECIPE_CATALOG.values()]


__all__ = ["get_recipe", "list_recipes", "DEFAULT_RECIPE_ID"]
