"""Helpers for computing a session-specific effective recipe."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


def _normalize_name(name: str | None) -> str:
    return (name or "").strip().lower()


def _coerce_overrides(
    overrides: dict[str, dict[str, Any]] | Iterable[dict[str, Any]] | None,
) -> Iterable[dict[str, Any]]:
    if overrides is None:
        return []
    if isinstance(overrides, dict):
        return overrides.values()
    return overrides


def _copy_ingredients(base_recipe: dict[str, Any]) -> list[dict[str, Any]]:
    ingredients = base_recipe.get("ingredients", [])
    return [deepcopy(ing) for ing in ingredients]


def _find_ingredient(ingredients: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    target_norm = _normalize_name(target)
    for ing in ingredients:
        if _normalize_name(ing.get("name")) == target_norm:
            return ing
    return None


def _parse_amount(override: dict[str, Any]) -> tuple[float | None, str | None]:
    amount = override.get("amount")
    if amount is None:
        amount = override.get("quantity")
    if amount is None and isinstance(override.get("ingredient"), dict):
        amount = override["ingredient"].get("quantity")
    unit = override.get("unit")
    if unit is None and isinstance(override.get("ingredient"), dict):
        unit = override["ingredient"].get("unit")
    try:
        if amount is None:
            return None, unit
        return float(amount), unit
    except (TypeError, ValueError):
        return None, unit


def _apply_serving_scale(
    ingredients: list[dict[str, Any]], base_servings: float | None, servings_override: float | None
) -> None:
    if not base_servings or not servings_override:
        return
    try:
        scale = float(servings_override) / float(base_servings)
    except (TypeError, ValueError, ZeroDivisionError):
        return
    for ing in ingredients:
        qty = ing.get("quantity")
        try:
            if qty is None:
                continue
            ing["quantity"] = float(qty) * scale
        except (TypeError, ValueError):
            continue


def build_effective_recipe(
    base_recipe: dict[str, Any],
    ingredient_overrides: dict[str, dict[str, Any]] | list[dict[str, Any]] | None = None,
    servings_override: float | int | None = None,
) -> dict[str, Any]:
    """Return a computed recipe after applying overrides and serving changes."""

    effective = deepcopy(base_recipe)
    ingredients = _copy_ingredients(base_recipe)

    for override in _coerce_overrides(ingredient_overrides):
        action = (override.get("action") or override.get("type") or "").lower()
        ingredient_meta = override.get("ingredient") or {}
        target_name = _normalize_name(ingredient_meta.get("name") or override.get("target"))

        if action == "add":
            ingredient = deepcopy(ingredient_meta or override.get("replacement") or {})
            if ingredient.get("name"):
                ingredients.append(ingredient)

        elif action == "remove":
            if not target_name:
                continue
            ingredients = [
                ing
                for ing in ingredients
                if _normalize_name(ing.get("name")) != target_name
            ]

        elif action == "update":
            if not target_name:
                continue
            matched = _find_ingredient(ingredients, target_name)
            if not matched:
                continue
            amount, unit = _parse_amount(override)
            if amount is not None:
                matched["quantity"] = amount
            if unit:
                matched["unit"] = unit

        elif action == "swap":
            replacement = override.get("replacement") or {}
            if not target_name or not replacement.get("name"):
                continue
            ingredients = [
                ing
                for ing in ingredients
                if _normalize_name(ing.get("name")) != target_name
            ]
            ingredients.append(deepcopy(replacement))

        # Future actions can be added here

    _apply_serving_scale(ingredients, base_recipe.get("servings"), servings_override)

    effective["ingredients"] = ingredients
    if servings_override is not None:
        effective["servings"] = servings_override
        effective["servings_source"] = "override"
    else:
        effective["servings_source"] = "base"

    effective["applied_overrides"] = list(_coerce_overrides(ingredient_overrides))

    return effective


__all__ = ["build_effective_recipe"]
