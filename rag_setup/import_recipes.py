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
HEADER_ALIASES = {
    "recipe": "Recipe",
    "title": "Recipe",
    "column_0": "Recipe",
    "content": "Content",
    "body": "Content",
    "column_1": "Content",
    "dish": "Dish",
    "stage": "Stages",
    "stages": "Stages",
    "foodpics": "food_pics",
    "food_pics": "food_pics",
    "food pics": "food_pics",
}
NORMALIZED_HEADERS = {
    "Recipe": "title",
    "Content": "body",
    "Dish": "dish",
    "Stages": "stage",
    "food_pics": "food_pics",
}
CLASSIFICATIONS = ["recipe_full", "recipe_partial", "note", "herb_tip", "post", "other"]
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
SECTION_HEADER_TOKENS = [
    "ingredients",
    "ingredient",
    "instructions",
    "directions",
    "preparation",
    "prep",
    "method",
    "steps",
    "notes",
    "note",
    "tips",
    "tip",
]
SECTION_HEADER_MAX_TOKENS = 40
SECTION_HEADER_MAX_PREFIX_WORDS = 5
ALLOWED_RECIPE_STAGES = {"Make ahead", "Prepare the meal"}


def normalize_headers(headers: Iterable[str] | None) -> list[str]:
    if headers is None:
        raise ValueError("CSV file has no headers")

    normalized: list[str] = []
    seen: dict[str, int] = {}
    for index, raw_header in enumerate(headers):
        cleaned = clean_header(raw_header)
        if not cleaned:
            cleaned = f"column_{index}"
        alias_key = cleaned.lower()
        canonical = HEADER_ALIASES.get(alias_key, cleaned)
        if canonical in seen:
            seen[canonical] += 1
            canonical = f"{canonical}_{seen[canonical]}"
        else:
            seen[canonical] = 0
        normalized.append(canonical)
    return normalized


def read_rows(csv_path: Path) -> Iterable[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        normalized_headers = normalize_headers(reader.fieldnames)
        validate_headers(normalized_headers)
        reader.fieldnames = normalized_headers
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
    ingredient_lines_raw, ingredient_flags = extract_ingredient_section_lines(normalized.get("body", ""))
    ingestion_flags = list(ingredient_flags)
    normalized["ingredient_lines_raw"] = ingredient_lines_raw
    missing_section = "missing_ingredients_section" in ingestion_flags
    if missing_section:
        normalized["ingredient_lines_source"] = "none"
        normalized["ingredient_lines_status"] = "missing_review_required"
    else:
        normalized["ingredient_lines_source"] = "section_lines"
        normalized["ingredient_lines_status"] = "present"

    if not ingredient_lines_raw and not missing_section:
        normalized["ingredient_lines_source"] = "none"
        normalized["ingredient_lines_status"] = "missing_review_required"
        ingestion_flags.append("missing_ingredients_section")
    stage_value = normalized.get("stage", "")
    stage_is_valid = stage_value in ALLOWED_RECIPE_STAGES
    normalized["stage_is_valid"] = stage_is_valid
    if not stage_is_valid and "invalid_recipe_stage" not in ingestion_flags:
        ingestion_flags.append("invalid_recipe_stage")
    normalized["ingestion_flags"] = ingestion_flags
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
        return "post"

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


def extract_ingredient_section_lines(content: str) -> tuple[list[str], list[str]]:
    """Return raw ingredient lines plus any ingestion flags."""

    lines = content.splitlines()
    ingredient_lines: list[str] = []
    ingestion_flags: list[str] = []
    collecting = False
    found_section = False

    for raw_line in lines:
        clean_line = raw_line.replace("\xa0", " ").replace("\\xa0", " ")
        header = detect_section_header(clean_line)
        if not collecting:
            if header in {"ingredient", "ingredients"}:
                collecting = True
                found_section = True
            continue

        if header and header not in {"ingredient", "ingredients"}:
            break
        if header in {"ingredient", "ingredients"}:
            # nested Ingredients header; keep collecting but skip the header line
            continue
        if not clean_line.strip():
            continue
        ingredient_lines.append(raw_line.rstrip("\r"))

    if not found_section:
        ingestion_flags.append("missing_ingredients_section")

    return ingredient_lines, ingestion_flags


def detect_section_header(line: str) -> str | None:
    normalized = normalize_header_for_matching(line)
    if not normalized:
        return None
    tokens = [part for part in re.split(r"\W+", normalized) if part]
    if not tokens:
        return None
    if len(tokens) > SECTION_HEADER_MAX_TOKENS:
        return None
    for token in SECTION_HEADER_TOKENS:
        for index, word in enumerate(tokens):
            if word == token and index <= SECTION_HEADER_MAX_PREFIX_WORDS:
                return token
    return None


def normalize_header_for_matching(line: str) -> str:
    if not line:
        return ""
    text = line.strip()
    if not text:
        return ""
    # Remove markdown heading markers, bullets, and checklist prefixes.
    text = re.sub(r"^[#>*+\-\s`]+", "", text)
    text = re.sub(r"^(?:\[[xX ]\])\s*", "", text)
    # Trim trailing punctuation commonly used around headings.
    text = text.strip().replace(' ', ' ')
    text = text.strip('*`_~')
    text = text.strip()
    text = re.sub(r'^\W+', '', text)
    text = re.sub(r'\W+$', '', text)
    text = re.sub(r"\s+", " ", text)
    return text.lower()


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
