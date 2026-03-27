"""Phase 1 raw ingestion for Backdrop recipe export."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "recipes" / "recipes.csv"
DEFAULT_OUTPUT = REPO_ROOT / "rag_setup" / "recipes_normalized.jsonl"
REQUIRED_HEADERS = ["Recipe", "Content", "Dish", "Stages", "food_pics"]
NORMALIZED_HEADERS = {
    "Recipe": "title",
    "Content": "body",
    "Dish": "dish",
    "Stages": "stage",
    "food_pics": "food_pics",
}
CLASSIFICATIONS = ["recipe_full", "recipe_partial", "note", "herb_tip", "other"]
SERVINGS_PATTERNS = [
    ("serves", r"serves\s+(?P<count>\d+(?:\.\d+)?)"),
    ("yield", r"yield\s+(?P<count>\d+(?:\.\d+)?)"),
    ("serving_size", r"serving size\s+(?P<count>\d+(?:\.\d+)?)(?:\s+\w+)?"),
]
HERB_WORDS = [
    "parsley",
    "cilantro",
    "mint",
    "dill",
    "basil",
    "oregano",
    "thyme",
    "rosemary",
    "sage",
    "chives",
    "tarragon",
]
AROMATIC_WORDS = ["garlic", "ginger", "scallion", "scallions", "green onion", "shallot"]


def read_rows(csv_path: Path) -> Iterable[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        validate_headers(reader.fieldnames)
        for row in reader:
            yield row


def clean_header(name: str | None) -> str:
    if not name:
        return ""
    return name.replace("\ufeff", "").strip()


def validate_headers(headers: Iterable[str] | None) -> None:
    if headers is None:
        raise ValueError("CSV file has no headers")
    cleaned = [clean_header(h) for h in headers]
    missing = [h for h in REQUIRED_HEADERS if h not in cleaned]
    if missing:
        raise ValueError(f"CSV missing required columns: {', '.join(missing)}")


def normalize_row(raw: dict[str, Any]) -> dict[str, Any]:
    cleaned_raw = {clean_header(k): v for k, v in raw.items()}
    normalized: dict[str, Any] = {}
    for source, target in NORMALIZED_HEADERS.items():
        value = cleaned_raw.get(source) or ""
        if target == "body":
            normalized[target] = value
        else:
            normalized[target] = value.strip()
    normalized["raw_checksum"] = compute_checksum(normalized)
    normalized["classification"] = classify_row(normalized)
    normalized["herb_mentions"] = extract_mentions(normalized.get("body", ""), HERB_WORDS)
    normalized["aromatic_mentions"] = extract_mentions(
        normalized.get("body", ""), AROMATIC_WORDS
    )
    normalized["ingredient_lines_raw"] = extract_ingredient_lines(normalized.get("body", ""))
    enriched = apply_serving_rules(normalized)
    warnings = list(validate_row(normalized))
    if warnings:
        enriched["warnings"] = warnings
    return enriched


def compute_checksum(normalized: dict[str, Any]) -> str:
    payload = json.dumps(
        {key: normalized.get(key, "") for key in NORMALIZED_HEADERS.values()},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def classify_row(row: dict[str, Any]) -> str:
    title = row.get("title", "").lower()
    body = row.get("body", "").lower()
    stage = row.get("stage", "").lower()
    if not title and not body:
        return "other"

    if stage == "still growing":
        return "other"

    herb_keywords = ["herb", "rosemary", "lavender", "cilantro", "parsley", "thyme", "sage"]
    herb_context = ["watering", "water", "soil", "pot", "planter", "grow", "garden", "care"]
    note_keywords = ["note", "tip", "ideas", "history", "welcome", "plan", "story", "accompany"]
    cooking_cues = [
        "roasted",
        "salad",
        "soup",
        "one pan",
        "bake",
        "chicken",
        "fish",
        "pasta",
        "curry",
        "dumplings",
        "recipe",
        "night",
        "skillet",
        "pita",
        "rice",
        "trout",
        "beans",
    ]

    has_ingredients = "ingredients" in body
    has_instructions = any(word in body for word in ["instructions", "directions", "prep time"])

    herb_match = any(keyword in title for keyword in herb_keywords) or any(
        keyword in body for keyword in herb_keywords
    )
    herb_context_match = any(keyword in body for keyword in herb_context)
    note_match = any(keyword in title for keyword in note_keywords) or any(
        keyword in body for keyword in note_keywords
    )
    cooking_match = has_ingredients or any(keyword in title for keyword in cooking_cues)

    if cooking_match:
        return "recipe_full" if (has_ingredients and has_instructions) else "recipe_partial"
    if herb_match and herb_context_match and not has_ingredients:
        return "herb_tip"
    if note_match:
        return "note"
    return "other"


def apply_serving_rules(row: dict[str, Any]) -> dict[str, Any]:
    classification = row.get("classification")
    body_lower = row.get("body", "").lower()
    explicit_servings = extract_servings(body_lower)
    row = dict(row)
    if explicit_servings is not None:
        row["servings"] = explicit_servings
        row["servings_inferred"] = False
        row["servings_source"] = "explicit"
        return row

    if classification in {"recipe_full", "recipe_partial"}:
        row["servings"] = 2
        row["servings_inferred"] = True
        row["servings_source"] = "default_rule"
    return row


def extract_servings(body: str) -> float | None:
    for tag, pattern in SERVINGS_PATTERNS:
        match = re.search(pattern, body)
        if match:
            try:
                value = float(match.group("count"))
                return value
            except (ValueError, TypeError):
                continue
    return None


def validate_row(row: dict[str, Any]) -> Iterable[str]:
    if not row["title"]:
        yield "missing_title"
    if not row["body"]:
        yield "missing_body"
    body = row.get("body", "")
    if looks_truncated(body):
        yield "possible_truncation"


def looks_truncated(body: str) -> bool:
    if not body:
        return False
    trimmed = body.strip()
    suspicious_endings = ("...", "Read more", "Continue reading", "→")
    if any(trimmed.endswith(token) for token in suspicious_endings):
        return True
    if "Click to read" in body or "http" in body and "Ingredients" not in body:
        return True
    return False


def extract_mentions(body: str, keywords: list[str]) -> list[str]:
    body_lower = body.lower()
    found = []
    for word in keywords:
        if word in body_lower:
            found.append(word)
    return found


def extract_ingredient_lines(body: str) -> list[str]:
    lines = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith("ingredients"):
            continue
        qty_tokens = [
            "tbsp",
            "tsp",
            "cup",
            "cups",
            "g",
            "gram",
            "grams",
            "ml",
            "ounce",
            "ounces",
            "oz",
            "teaspoon",
            "tablespoon",
            "kg",
            "lb",
            "pound",
            "serving",
            "servings",
        ]
        has_quantity_token = any(token in lower for token in qty_tokens)
        starts_like_list = lower.startswith(('- ', '•', '*'))
        has_digit = any(ch.isdigit() for ch in lower)
        if starts_like_list and (has_quantity_token or has_digit):
            lines.append(line)
        elif has_quantity_token and has_digit:
            lines.append(line)
    return lines


def write_output(rows: Iterable[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import raw Backdrop recipes CSV")
    parser.add_argument("--csv", dest="csv", default=DEFAULT_INPUT, type=Path)
    parser.add_argument("--output", dest="output", default=DEFAULT_OUTPUT, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        raise SystemExit(1)

    normalized_rows = [normalize_row(row) for row in read_rows(args.csv)]
    write_output(normalized_rows, args.output)
    print(
        f"Imported {len(normalized_rows)} rows from {args.csv} -> {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
