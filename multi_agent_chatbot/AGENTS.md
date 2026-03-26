# AGENTS: Recipe Seed Export & Loader

This document explains how Codex should interact with the recipe seed ingestion pipeline described in `SPEC-1-Recipe Seed Export and Loader`.

## Directory Layout

The working chatbot lives in `multi_agent_chatbot/`. Recipe CSV exports are stored in the sibling `recipes/` directory at the repository root. File references assume you are executing commands from `multi_agent_chatbot/` unless noted otherwise.

```
ai-agents-crash-course/
├── multi_agent_chatbot/
│   ├── agentic_chatbot.py
│   ├── nutrition_agent.py
│   ├── load_calories.py         # entry point for recipe ingestion
│   ├── recipe_loader.py         # loader implementation + helpers
│   ├── tests/
│   │   └── fixtures/recipes_seed_sample.csv
└── recipes/
    └── <your Backdrop export>.csv
```

> **Fixture note:** the committed sample CSV lives in `tests/fixtures/recipes_seed_sample.csv` for portability. Copy it into `../recipes/` when you want to run the loader without generating a fresh export.

## CSV Contract

The loader expects a UTF-8 CSV with a header row containing the following columns (names are normalized to lowercase snake_case, but please keep them stable):

| column        | required | notes                                             |
|---------------|----------|---------------------------------------------------|
| `nid`         | optional | When present, becomes the deterministic `source_id`
| `title`       | ✔        | Recipe title (blank headers are automatically aliased to `title`/`body`).
| `body`        | ✔        | Plain text body. HTML is stripped during ingest.
| `dish`        | ✔        | High-level dish or category label.
| `stage`       | ✔        | Prep/meal stage (e.g., `Make ahead`, `Post-game`).
| `source_url`  | optional | Permalink back to the CMS entry (defaulted to empty when missing in exports).
| `food_pics`   | optional | Raw image field exported from Backdrop (pipe/comma-delimited). Used to derive image metadata.

Additional columns are copied into the metadata payload automatically, so we can extend the schema later (e.g., cuisine, sport tags, macros).

## Normalization Rules

1. Column names are normalized to lowercase snake_case; `stages` is aliased to `stage`.
2. Leading/trailing whitespace is trimmed for all fields.
3. Bodies are unescaped, stripped of basic HTML tags, and collapsed to single spaces per line.
4. `source_id` is `recipe_<nid>` when `nid` exists, otherwise `recipe_<first_12_chars_of_checksum>`.
5. `raw_row_checksum` is a SHA-256 hex digest of the normalized row. Duplicate rows share the same checksum, enabling idempotent reloads.
6. `document_text` is composed as:

```
Title: <title>
Dish: <dish>
Stage: <stage>
Source URL: <source_url or 'N/A'>
Body:
<body>
```

7. If a `food_pics` column is present, the loader
   * stores the trimmed raw value as `food_pics_raw`
   * splits it into `image_urls` (pipe/comma-separated tokens, invalid URLs dropped)
   * sets `primary_image_url`, `image_count`, and `has_images` helper fields.
8. All normalized fields plus any extra columns are stored in the Chroma metadata blob so agents can filter on them later.

## Recipe Schema Helpers

The loader exposes a small schema toolkit in `recipe_loader.py`:

- `normalize_recipe_row(row: dict[str, str]) -> NormalizedRecipe`
  - Cleans and validates a CSV row, computes the checksum + deterministic `source_id`, parses dish/stage tags, and derives image metadata.
- `recipe_to_record(recipe: NormalizedRecipe) -> RecipeRecord`
  - Converts the normalized object into a Chroma-ready payload (document text + metadata dict) while preserving extra CSV fields.

`NormalizedRecipe` is a frozen dataclass with dependable fields (`title`, `body`, `dish_terms`, `stage_tags`, `food_pics_raw`, `image_urls`, `extra_fields`, etc.), making it easy to reason about transformations or add new derived attributes before they reach the vector store.

## Loader Usage

Run the loader from the `multi_agent_chatbot/` directory. By default it looks for `../recipes/recipes.csv`. Use `--csv` to point at a specific export and `--collection` if you want a non-default Chroma collection name. The loader will error if the file is missing or if required columns are absent.

```
source venv/bin/activate
python load_calories.py --csv ../recipes/recipes_seed_sample.csv
```

Environment variables are not required for ingestion. The Chroma database lives at `../chroma/` by default.

## Tests

Unit tests exercise the CSV parser and normalization logic without touching a real Chroma collection. Run them via:

```
source venv/bin/activate
python -m unittest tests.test_recipe_loader
```

## Do / Do Not

- ✅ **Do** update this document if the CSV contract changes.
- ✅ **Do** commit representative CSV fixtures (under `tests/fixtures/`) for deterministic tests.
- ✅ **Do** keep ingestion offline (no live CMS/API calls for MVP).
- ❌ **Do not** connect directly to Backdrop databases or authenticated endpoints from Codex.
- ❌ **Do not** rename required columns without coordinating schema + loader updates.

## Future Extensions

A live API synchronization mode can be layered on later by reusing the `RecipeLoader` normalization helpers. The agent layer consumes Chroma documents only, so no chatbot code needs to change when a fresh CSV is ingested.
