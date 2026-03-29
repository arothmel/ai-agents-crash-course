"""Runtime recipe catalog loaded from structured ingestion output."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable


CATALOG_PATH = Path(__file__).resolve().with_name("runtime_recipes.json")
PREFERRED_DEFAULT_TITLE = "black eyed peas recipe (greek-style)"


def _load_catalog() -> dict[str, dict[str, Any]]:
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(
            f"Runtime catalog not found: {CATALOG_PATH}. Run build_runtime_catalog.py first."
        )
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    catalog: dict[str, dict[str, Any]] = {}
    for entry in data:
        entry_id = entry.get("id")
        if not entry_id:
            continue
        catalog[entry_id] = {
            "id": entry_id,
            "title": entry.get("title"),
            "servings": entry.get("servings", 2),
            "ingredients": entry.get("ingredients", []),
            "ingredient_lines_raw": entry.get("ingredient_lines_raw", []),
        }
    if not catalog:
        raise ValueError("Runtime catalog is empty; no recipes loaded.")
    return catalog


def _sorted_recipe_ids(entries: Iterable[dict[str, Any]]) -> list[str]:
    sortable = []
    for entry in entries:
        title = (entry.get("title") or "").strip().lower()
        sortable.append((title, entry["id"]))
    sortable.sort()
    return [item[1] for item in sortable]


_RUNTIME_CATALOG = _load_catalog()
_SORTED_IDS = _sorted_recipe_ids(_RUNTIME_CATALOG.values())
preferred = next(
    (
        recipe_id
        for recipe_id in _SORTED_IDS
        if (_RUNTIME_CATALOG[recipe_id].get("title") or "").strip().lower()
        == PREFERRED_DEFAULT_TITLE
    ),
    None,
)
DEFAULT_RECIPE_ID = preferred or (_SORTED_IDS[0] if _SORTED_IDS else next(iter(_RUNTIME_CATALOG.keys())))


def get_recipe(recipe_id: str | None) -> Dict[str, Any]:
    recipe = _RUNTIME_CATALOG.get(recipe_id or DEFAULT_RECIPE_ID)
    if not recipe:
        raise KeyError(f"Unknown recipe id: {recipe_id}")
    return deepcopy(recipe)


def list_recipes() -> list[dict[str, Any]]:
    return [deepcopy(_RUNTIME_CATALOG[recipe_id]) for recipe_id in _SORTED_IDS]


def resolve_recipe_id_by_title(title: str | None) -> str | None:
    if not title:
        return None
    target = title.strip().lower()
    if not target:
        return None
    for recipe_id, recipe in _RUNTIME_CATALOG.items():
        recipe_title = (recipe.get("title") or "").strip().lower()
        if recipe_title == target:
            return recipe_id
    return None


__all__ = ["get_recipe", "list_recipes", "DEFAULT_RECIPE_ID", "resolve_recipe_id_by_title"]
