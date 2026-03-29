"""Build a runtime-ready recipe catalog from normalized ingestion data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "rag_setup" / "recipes_normalized.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "multi_agent_chatbot" / "runtime_recipes.json"
MIN_STRUCTURED_INGREDIENTS = 3


UNIT_ALIASES = {
    "g": "g",
    "gram": "g",
    "grams": "g",
    "kg": "kg",
    "ml": "ml",
    "l": "l",
    "liter": "l",
    "liters": "l",
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "tsp": "tsp",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "tbsp": "tbsp",
    "cup": "cup",
    "cups": "cup",
    "oz": "oz",
    "ounce": "oz",
    "ounces": "oz",
    "lb": "lb",
    "lbs": "lb",
    "pound": "lb",
    "pounds": "lb",
    "clove": "clove",
    "cloves": "clove",
    "can": "can",
    "cans": "can",
    "package": "package",
    "packages": "package",
    "slice": "slice",
    "slices": "slice",
    "piece": "piece",
    "pieces": "piece",
    "sprig": "sprig",
    "sprigs": "sprig",
    "bunch": "bunch",
    "bunches": "bunch",
    "head": "head",
    "heads": "head",
    "stick": "stick",
    "sticks": "stick",
}

SPECIAL_UNIT_ALIASES = {
    "T": "tbsp",
    "T.": "tbsp",
    "t": "tsp",
    "t.": "tsp",
    "Tbsp": "tbsp",
    "Tbsp.": "tbsp",
    "Tbs": "tbsp",
    "Tbl": "tbsp",
}

SECTION_HEADERS = {"ingredients", "toppings", "prepare", "instructions", "notes"}
UNICODE_FRACTIONS = {
    "½": "1/2",
    "¼": "1/4",
    "¾": "3/4",
    "⅓": "1/3",
    "⅔": "2/3",
    "⅛": "1/8",
}


@dataclass
class RuntimeRecipe:
    recipe_id: str
    title: str
    servings: float
    ingredients: list[dict[str, object]]
    ingredient_lines_raw: list[str]


def read_normalized_rows(path: Path) -> Iterable[dict]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def normalize_fraction_tokens(text: str) -> str:
    for char, replacement in UNICODE_FRACTIONS.items():
        text = text.replace(char, replacement)
    text = re.sub(r"(?<=\d)-(\d/\d)", r" \1", text)
    return text


def clean_line(text: str) -> str:
    stripped = text.replace("\xa0", " ")
    stripped = normalize_fraction_tokens(stripped)
    stripped = re.sub(r"^[\s\-•*▢▪‣●◦·]+", "", stripped)
    stripped = stripped.strip()
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped


QUANTITY_PATTERN = re.compile(
    r"^(?P<quantity>\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\b(?P<rest>.*)$"
)


def parse_quantity(value: str) -> float:
    value = value.strip()
    if " " in value and "/" in value:
        parts = value.split()
        total = Fraction(0)
        for part in parts:
            total += Fraction(part)
        return float(total)
    return float(Fraction(value))


def parse_ingredient_line(line: str) -> dict[str, object] | None:
    text = clean_line(line)
    if not text or not any(char.isdigit() for char in text):
        return None
    lowered = text.lower()
    if any(lowered.startswith(header) for header in SECTION_HEADERS):
        return None

    match = QUANTITY_PATTERN.match(text)
    if not match:
        return None

    quantity_text = match.group("quantity").strip()
    rest = match.group("rest").strip()
    if not rest:
        return None

    try:
        quantity = parse_quantity(quantity_text)
    except (ValueError, ZeroDivisionError):
        return None

    tokens = rest.split()
    if not tokens:
        return None

    unit_token_raw = re.sub(r"[,:;.]$", "", tokens[0]).strip()
    unit_token_lower = unit_token_raw.lower()
    unit = UNIT_ALIASES.get(unit_token_lower)
    if not unit:
        unit = SPECIAL_UNIT_ALIASES.get(unit_token_raw) or SPECIAL_UNIT_ALIASES.get(
            unit_token_lower
        )
    name_tokens = tokens[1:] if unit else tokens
    name = " ".join(name_tokens).strip()
    if "," in name:
        name = name.split(",", 1)[0].strip()
    if not name:
        return None

    return {
        "name": name,
        "quantity": round(quantity, 4),
        "unit": unit,
    }


def build_runtime_entry(row: dict) -> tuple[RuntimeRecipe | None, str | None]:
    if row.get("classification") != "recipe_full":
        return None, "not_recipe_full"
    if row.get("ingredient_lines_status") != "present":
        return None, "missing_ingredient_section"
    lines = row.get("ingredient_lines_raw") or []
    structured: list[dict[str, object]] = []
    for raw_line in lines:
        parsed = parse_ingredient_line(raw_line)
        if parsed:
            structured.append(parsed)
    if len(structured) < MIN_STRUCTURED_INGREDIENTS:
        return None, "insufficient_structured_ingredients"
    servings = row.get("servings") or 2
    recipe_id = row.get("raw_checksum") or row.get("title")
    title = row.get("title") or recipe_id
    if not recipe_id:
        return None, "missing_recipe_id"
    return (
        RuntimeRecipe(
            recipe_id=recipe_id,
            title=title,
            servings=servings,
            ingredients=structured,
            ingredient_lines_raw=lines,
        ),
        None,
    )


def write_runtime_catalog(entries: list[RuntimeRecipe], output_path: Path) -> None:
    payload = [
        {
            "id": entry.recipe_id,
            "title": entry.title,
            "servings": entry.servings,
            "ingredients": entry.ingredients,
            "ingredient_lines_raw": entry.ingredient_lines_raw,
        }
        for entry in entries
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ready: list[RuntimeRecipe] = []
    skipped: dict[str, int] = {}
    for row in read_normalized_rows(DEFAULT_INPUT):
        entry, reason = build_runtime_entry(row)
        if entry:
            ready.append(entry)
        else:
            if reason:
                skipped[reason] = skipped.get(reason, 0) + 1
    write_runtime_catalog(ready, DEFAULT_OUTPUT)
    print(f"Runtime-ready recipes: {len(ready)} -> {DEFAULT_OUTPUT}")
    if skipped:
        print("Skipped recipes:")
        for reason, count in sorted(skipped.items()):
            print(f"  {reason}: {count}")


if __name__ == "__main__":
    main()
