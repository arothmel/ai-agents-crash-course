"""Session helpers for conversational recipe overrides."""

from __future__ import annotations

import re
from typing import Any, Dict

from effective_recipe import build_effective_recipe
from nutrition_calculator import NutritionCalculator
from recipe_catalog import DEFAULT_RECIPE_ID, get_recipe

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
    if not state["working_recipe_id"]:
        state["working_recipe_id"] = DEFAULT_RECIPE_ID
    if not state["working_ingredients"]:
        base = get_recipe(state["working_recipe_id"])
        state["working_ingredients"] = [ing["name"] for ing in base.get("ingredients", [])]
    return state


def parse_command(message: str) -> dict | None:
    text = _strip_trailing(message)
    if not text:
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
    else:
        status = "No override applied."

    base_recipe = get_recipe(state["working_recipe_id"])
    effective = build_effective_recipe(
        base_recipe, state.get("ingredient_overrides"), state.get("servings_override")
    )
    state["working_ingredients"] = [ing["name"] for ing in effective.get("ingredients", [])]

    nutrition = nutrition_calculator.calculate(effective)

    return {
        "status": status,
        "effective_recipe": effective,
        "nutrition": nutrition,
    }


__all__ = ["ensure_state", "parse_command", "apply_command"]
