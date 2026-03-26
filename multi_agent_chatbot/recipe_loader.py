from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

try:  # pragma: no cover - optional at import time for unit tests
    import chromadb
except ImportError:  # pragma: no cover - handled at runtime if needed
    chromadb = None  # type: ignore[assignment]

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
DEFAULT_RECIPES_DIR = REPO_ROOT / "recipes"
DEFAULT_CHROMA_PATH = REPO_ROOT / "chroma"
DEFAULT_COLLECTION_NAME = "recipes_db"
DEFAULT_CSV_BASENAME = "recipes.csv"
REQUIRED_COLUMNS = {"title", "body", "dish", "stage"}
HEADER_ALIASES = {
    "stages": "stage",
    "column_0": "title",
    "column_1": "body",
}
HTML_TAG_RE = re.compile(r"<[^>]+>")
MULTISPACE_RE = re.compile(r"\s+")
IMAGE_SPLIT_RE = re.compile(r"[|\n,]")
IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|gif|bmp|webp|avif|svg)(?=$|[?#])", re.IGNORECASE)
BASE_FIELDS = {
    "title",
    "body",
    "dish",
    "stage",
    "source_url",
    "nid",
    "food_pics",
}


@dataclass(frozen=True)
class NormalizedRecipe:
    source_id: str
    title: str
    body: str
    body_length: int
    dish: str
    dish_terms: list[str]
    stage: str
    stage_tags: list[str]
    source_url: str
    nid: str | None
    raw_row_checksum: str
    food_pics_raw: str
    image_urls: list[str]
    primary_image_url: str | None
    image_count: int
    has_images: bool
    extra_fields: dict[str, str]


@dataclass(frozen=True)
class RecipeRecord:
    source_id: str
    document_text: str
    metadata: dict[str, Any]


def _metadata_scalar(value: Any) -> Any:
    """Coerce metadata values into scalars acceptable by Chroma."""
    if isinstance(value, (list, tuple, set, frozenset)):
        return json.dumps(list(value))
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return value


def _ensure_scalar_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: _metadata_scalar(value) for key, value in metadata.items()}


def clean_value(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


def clean_body(value: str) -> str:
    text = html.unescape(value)
    text = text.replace("\xa0", " ")
    text = HTML_TAG_RE.sub(" ", text)
    text = MULTISPACE_RE.sub(" ", text)
    return text.strip()


def compose_document_text(title: str, dish: str, stage: str, source_url: str, body: str) -> str:
    parts = [
        f"Title: {title}",
        f"Dish: {dish}" if dish else None,
        f"Stage: {stage}" if stage else None,
        f"Source URL: {source_url or 'N/A'}",
        "Body:",
        body,
    ]
    return "\n".join(part for part in parts if part is not None)


def split_terms(value: str) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[,;]", value)
    return [part.strip() for part in parts if part.strip()]


def checksum_row(row: dict[str, str]) -> str:
    encoded = json.dumps(row, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_image_urls(value: str) -> list[str]:
    if not value:
        return []
    candidates = IMAGE_SPLIT_RE.split(value)
    urls: list[str] = []
    for candidate in candidates:
        url = candidate.strip()
        if not url:
            continue
        if looks_like_image(url):
            urls.append(url)
    return urls


def looks_like_image(url: str) -> bool:
    if not IMAGE_EXT_RE.search(url):
        return False
    if url.startswith(("http://", "https://", "/", "./", "../")):
        return True
    return True


def normalize_recipe_row(row: dict[str, str]) -> NormalizedRecipe:
    normalized_row = {key: clean_value(value) for key, value in row.items()}
    checksum = checksum_row(normalized_row)

    title = normalized_row.get("title", "")
    raw_body = normalized_row.get("body", "")
    body = clean_body(raw_body)
    dish = normalized_row.get("dish", "")
    stage = normalized_row.get("stage", "")
    source_url = normalized_row.get("source_url", "")
    nid_value = normalized_row.get("nid") or None
    if nid_value:
        nid_value = nid_value.strip()
    source_id = f"recipe_{nid_value}" if nid_value else f"recipe_{checksum[:12]}"
    dish_terms = split_terms(dish)
    stage_tags = split_terms(stage)

    pics_raw = normalized_row.get("food_pics", "")
    image_urls = parse_image_urls(pics_raw)

    extra_fields: dict[str, str] = {}
    for key, value in normalized_row.items():
        if key in BASE_FIELDS:
            continue
        if not value:
            continue
        extra_fields.setdefault(key, value)

    return NormalizedRecipe(
        source_id=source_id,
        title=title,
        body=body,
        body_length=len(body),
        dish=dish,
        dish_terms=dish_terms,
        stage=stage,
        stage_tags=stage_tags,
        source_url=source_url,
        nid=nid_value,
        raw_row_checksum=checksum,
        food_pics_raw=pics_raw,
        image_urls=image_urls,
        primary_image_url=image_urls[0] if image_urls else None,
        image_count=len(image_urls),
        has_images=bool(image_urls),
        extra_fields=extra_fields,
    )


def recipe_to_record(recipe: NormalizedRecipe) -> RecipeRecord:
    document_text = compose_document_text(
        recipe.title,
        recipe.dish,
        recipe.stage,
        recipe.source_url,
        recipe.body,
    )

    metadata: dict[str, Any] = {
        "source_id": recipe.source_id,
        "title": recipe.title,
        "dish": recipe.dish,
        "dish_terms": recipe.dish_terms,
        "stage": recipe.stage,
        "stage_tags": recipe.stage_tags,
        "source_url": recipe.source_url,
        "nid": recipe.nid or "",
        "raw_row_checksum": recipe.raw_row_checksum,
        "body_length": recipe.body_length,
        "food_pics_raw": recipe.food_pics_raw,
        "image_urls": recipe.image_urls,
        "primary_image_url": recipe.primary_image_url or "",
        "image_count": recipe.image_count,
        "has_images": recipe.has_images,
    }

    for key, value in recipe.extra_fields.items():
        if key in metadata:
            continue
        metadata[key] = value

    metadata = _ensure_scalar_metadata(metadata)

    return RecipeRecord(
        source_id=recipe.source_id,
        document_text=document_text,
        metadata=metadata,
    )


class RecipeLoader:
    """Load recipe CSV exports into Chroma."""

    def __init__(
        self,
        csv_path: Path,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        chroma_path: Path | None = None,
        collection: Any | None = None,
    ) -> None:
        self.csv_path = csv_path
        self.collection_name = collection_name
        self.chroma_path = chroma_path or DEFAULT_CHROMA_PATH
        self._collection = collection

    def load(self) -> list[RecipeRecord]:
        records = self.load_records()
        if not records:
            print("No recipe rows found; nothing to ingest.")
            return []

        collection = self._ensure_collection()
        collection.upsert(
            ids=[record.source_id for record in records],
            documents=[record.document_text for record in records],
            metadatas=[record.metadata for record in records],
        )

        print(
            f"Upserted {len(records)} recipes into collection '{self.collection_name}'."
        )
        return records

    def load_records(self) -> list[RecipeRecord]:
        rows = self._read_csv_rows(self.csv_path)
        records: list[RecipeRecord] = []
        for row in rows:
            normalized = normalize_recipe_row(row)
            record = recipe_to_record(normalized)
            records.append(record)
        return records

    def _ensure_collection(self):
        if self._collection is not None:
            return self._collection

        if chromadb is None:  # pragma: no cover - exercised in runtime usage
            raise ImportError(
                "chromadb is required to persist recipes. Install dependencies first."
            )
        client = chromadb.PersistentClient(path=str(self.chroma_path))
        self._collection = client.get_or_create_collection(self.collection_name)
        return self._collection

    def _read_csv_rows(self, csv_path: Path) -> list[dict[str, str]]:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            try:
                raw_headers = next(reader)
            except StopIteration:
                return []

            normalized_headers = self._normalize_headers(raw_headers)
            missing_columns = REQUIRED_COLUMNS - set(normalized_headers)
            if missing_columns:
                raise ValueError(
                    f"CSV missing required columns: {', '.join(sorted(missing_columns))}"
                )

            rows: list[dict[str, str]] = []
            for raw_row in reader:
                if not any(cell.strip() for cell in raw_row):
                    continue
                padded = raw_row + [""] * (len(normalized_headers) - len(raw_row))
                row_dict = {
                    normalized_headers[i]: padded[i].strip()
                    for i in range(len(normalized_headers))
                }
                rows.append(row_dict)
        return rows

    def _normalize_headers(self, headers: Sequence[str]) -> list[str]:
        normalized: list[str] = []
        seen: dict[str, int] = {}
        for index, header in enumerate(headers):
            normalized_name = self._normalize_single_header(header, index)
            normalized_name = HEADER_ALIASES.get(normalized_name, normalized_name)
            if normalized_name in seen:
                seen[normalized_name] += 1
                normalized_name = f"{normalized_name}_{seen[normalized_name]}"
            else:
                seen[normalized_name] = 0
            normalized.append(normalized_name)
        return normalized

    @staticmethod
    def _normalize_single_header(header: str, index: int) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", header.strip().lower())
        slug = slug.strip("_")
        if not slug:
            slug = f"column_{index}"
        return slug


def resolve_csv_path(csv_arg: str | None, recipes_dir_arg: str | None) -> Path:
    if csv_arg:
        path = Path(csv_arg).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")
        return path

    recipes_dir = (
        Path(recipes_dir_arg).expanduser() if recipes_dir_arg else DEFAULT_RECIPES_DIR
    )
    default_candidate = recipes_dir / DEFAULT_CSV_BASENAME
    if default_candidate.exists():
        return default_candidate

    csv_files = sorted(recipes_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(
            f"No CSV files found in {recipes_dir}. Provide --csv to specify a file."
        )
    return csv_files[0]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load recipe CSV exports into Chroma.")
    parser.add_argument(
        "--csv",
        dest="csv",
        help="Path to a specific CSV export. Default: ../recipes/recipes.csv",
    )
    parser.add_argument(
        "--recipes-dir",
        dest="recipes_dir",
        help="Directory that stores Backdrop CSV exports (default: ../recipes).",
    )
    parser.add_argument(
        "--collection",
        dest="collection",
        default=DEFAULT_COLLECTION_NAME,
        help=f"Chroma collection name (default: {DEFAULT_COLLECTION_NAME}).",
    )
    parser.add_argument(
        "--chroma-path",
        dest="chroma_path",
        help="Override the Chroma persistent path (default: ../chroma).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        csv_path = resolve_csv_path(args.csv, args.recipes_dir)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))

    loader = RecipeLoader(
        csv_path=csv_path,
        collection_name=args.collection,
        chroma_path=Path(args.chroma_path).expanduser() if args.chroma_path else None,
    )
    loader.load()


if __name__ == "__main__":
    main()
