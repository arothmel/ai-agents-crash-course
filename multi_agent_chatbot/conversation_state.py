"""Session helpers for conversational recipe overrides."""

from __future__ import annotations

import re
from typing import Any, Dict

from effective_recipe import build_effective_recipe
from nutrition_calculator import NutritionCalculator
from recipe_catalog import DEFAULT_RECIPE_ID, get_recipe, resolve_recipe_id_by_title
from retrieval import build_nutrition_input

_NORMALIZE_PUNCT_RE = re.compile(r"[.!?]+$")
ADD_RE = re.compile(r"^(?:please\s+)?add\s+(?P<name>.+)$", re.IGNORECASE)
REMOVE_RE = re.compile(r"^(?:please\s+)?remove\s+(?P<name>.+)$", re.IGNORECASE)
USE_RE = re.compile(
    r"^use\s+(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>[a-zA-Z]+)?\s+(?P<name>.+)$",
    re.IGNORECASE,
)
SERVINGS_RE = re.compile(
    r"^make\s+(?:it|this)?\s*for\s+(?P<count>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
RESET_RE = re.compile(r"^reset(?:\s+changes)?$", re.IGNORECASE)
USE_RECIPE_RE = re.compile(r"^use\s+recipe:\s*(?P<title>.+)$", re.IGNORECASE)


nutrition_calculator = NutritionCalculator()


def _strip_trailing(text: str) -> str:
    return _NORMALIZE_PUNCT_RE.sub("", text.strip())


def _normalize_name(name: str | None) -> str:
    return (name or "").strip().lower()


def ensure_state(state: dict | None) -> dict:
    if state is None:
        state = {}
    state.setdefault("working_recipe_id", DEFAULT_RECIPE_ID)
    state.setdefault("ingredient_overrides", {})
    state.setdefault("servings_override", None)
    state.setdefault("working_ingredients", None)
    state.setdefault("ingredient_lines_current", None)
    if not state["working_recipe_id"]:
        state["working_recipe_id"] = DEFAULT_RECIPE_ID
    if not state["working_ingredients"]:
        base = get_recipe(state["working_recipe_id"])
        state["working_ingredients"] = [ing["name"] for ing in base.get("ingredients", [])]
    return state


def _stringify_quantity(value: Any) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return str(number).rstrip("0").rstrip(".")


def _format_ingredient_line(ingredient: dict[str, Any]) -> str:
    name = (ingredient.get("name") or "").strip()
    qty = _stringify_quantity(ingredient.get("quantity") or ingredient.get("amount"))
    unit = (ingredient.get("unit") or "").strip()
    parts = [part for part in [qty, unit, name] if part]
    line = " ".join(parts)
    return line if line else name


def _lines_from_ingredients(ingredients: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for ingredient in ingredients:
        if not ingredient.get("name"):
            continue
        lines.append(_format_ingredient_line(ingredient))
    return lines


def parse_command(message: str) -> dict | None:
    text = _strip_trailing(message)
    if not text:
        return None
    match = USE_RECIPE_RE.match(text)
    if match:
        title = match.group("title").strip()
        if title:
            return {"type": "select_recipe", "title": title}
        return None
    if RESET_RE.match(text):
        return {"type": "reset"}
    match = ADD_RE.match(text)
    if match:
        return {"type": "add", "ingredient": match.group("name").strip()}
    match = REMOVE_RE.match(text)
    if match:
        return {"type": "remove", "ingredient": match.group("name").strip()}
    match = USE_RE.match(text)
    if match:
        amount = float(match.group("amount"))
        unit = match.group("unit")
        ingredient = match.group("name").strip()
        return {
            "type": "update_amount",
            "ingredient": ingredient,
            "amount": amount,
            "unit": unit.strip() if unit else None,
        }
    match = SERVINGS_RE.match(text)
    if match:
        count = float(match.group("count"))
        return {"type": "servings", "servings": count}
    return None


def _set_override(state: dict, ingredient: str, override: dict[str, Any]) -> None:
    key = _normalize_name(ingredient)
    state.setdefault("ingredient_overrides", {})
    state["ingredient_overrides"][key] = override


def _get_override(state: dict, ingredient: str) -> dict | None:
    overrides = state.get("ingredient_overrides") or {}
    return overrides.get(_normalize_name(ingredient))


def _remove_override(state: dict, ingredient: str) -> None:
    overrides = state.get("ingredient_overrides") or {}
    overrides.pop(_normalize_name(ingredient), None)


def apply_command(state: dict, command: dict) -> dict:
    state = ensure_state(state)
    action_type = command.get("type")
    status = ""

    if action_type == "reset":
        state["ingredient_overrides"] = {}
        state["servings_override"] = None
        state["ingredient_lines_current"] = None
        base = get_recipe(state["working_recipe_id"])
        state["working_ingredients"] = [ing["name"] for ing in base.get("ingredients", [])]
        status = "All overrides cleared."
    elif action_type == "add":
        ingredient = command["ingredient"].strip()
        override = {
            "action": "add",
            "ingredient": {"name": ingredient},
        }
        _set_override(state, ingredient, override)
        status = f"Prepared to add {ingredient.title()}."
    elif action_type == "remove":
        ingredient = command["ingredient"].strip()
        existing = _get_override(state, ingredient)
        if existing and existing.get("action") == "add":
            _remove_override(state, ingredient)
        else:
            override = {"action": "remove", "ingredient": {"name": ingredient}}
            _set_override(state, ingredient, override)
        status = f"Marked {ingredient.title()} for removal."
    elif action_type == "update_amount":
        ingredient = command["ingredient"].strip()
        amount = command.get("amount")
        unit = command.get("unit")
        existing = _get_override(state, ingredient)
        if existing and existing.get("action") == "add":
            existing.setdefault("ingredient", {}).update(
                {"name": ingredient, "quantity": amount, "unit": unit}
            )
        else:
            override = {
                "action": "update",
                "ingredient": {"name": ingredient},
                "amount": amount,
                "unit": unit,
            }
            _set_override(state, ingredient, override)
        unit_text = f" {unit}" if unit else ""
        status = f"Set {ingredient.title()} to {amount}{unit_text}."
    elif action_type == "servings":
        state["servings_override"] = command.get("servings")
        status = f"Serving override set to {command.get('servings')}"
    elif action_type == "select_recipe":
        title = (command.get("title") or "").strip()
        recipe_id = resolve_recipe_id_by_title(title)
        if recipe_id:
            state["working_recipe_id"] = recipe_id
            state["ingredient_overrides"] = {}
            state["servings_override"] = None
            state["ingredient_lines_current"] = None
            status = f"Switched to recipe: {title}"
        else:
            status = f"Recipe not found: {title}" if title else "Recipe title missing."
    else:
        status = "No override applied."

    base_recipe = get_recipe(state["working_recipe_id"])
    effective = build_effective_recipe(
        base_recipe, state.get("ingredient_overrides"), state.get("servings_override")
    )
    state["working_ingredients"] = [ing["name"] for ing in effective.get("ingredients", [])]

    derived_lines = _lines_from_ingredients(effective.get("ingredients", []))
    base_lines = list(base_recipe.get("ingredient_lines_raw") or [])
    has_overrides = bool(state.get("ingredient_overrides"))
    has_servings_override = state.get("servings_override") is not None
    if derived_lines and (has_overrides or has_servings_override or not base_lines):
        state["ingredient_lines_current"] = derived_lines
    else:
        state["ingredient_lines_current"] = None

    recipe_for_lines = dict(base_recipe)
    current_lines = state.get("ingredient_lines_current")
    if current_lines:
        recipe_for_lines["ingredient_lines_current"] = current_lines
    nutrition_input = build_nutrition_input(
        base_recipe.get("id"), recipe_for_lines, mode="current"
    )
    nutrition = nutrition_calculator.calculate(effective)

    return {
        "status": status,
        "effective_recipe": effective,
        "nutrition": nutrition,
        "nutrition_input": nutrition_input,
    }


__all__ = ["ensure_state", "parse_command", "apply_command"]
