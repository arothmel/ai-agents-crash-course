import csv
import json
import tempfile
import unittest
from pathlib import Path

from recipe_loader import (
    RecipeLoader,
    normalize_recipe_row,
    recipe_to_record,
)


FIXTURE_CSV = Path(__file__).resolve().parent / "fixtures" / "recipes_seed_sample.csv"


class FakeCollection:
    def __init__(self) -> None:
        self.upserts: list[tuple[list[str], list[str], list[dict]] ] = []

    def upsert(self, ids, documents, metadatas):  # type: ignore[no-untyped-def]
        self.upserts.append((list(ids), list(documents), list(metadatas)))


class RecipeLoaderTests(unittest.TestCase):
    def test_missing_required_columns_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_csv = Path(tmpdir) / "bad.csv"
            bad_csv.write_text("title,body\nFoo,Bar\n", encoding="utf-8")

            loader = RecipeLoader(csv_path=bad_csv)
            with self.assertRaises(ValueError):
                loader.load_records()

    def test_load_records_normalizes_rows(self) -> None:
        loader = RecipeLoader(csv_path=FIXTURE_CSV)
        records = loader.load_records()

        self.assertEqual(len(records), 3)
        first = records[0]
        self.assertEqual(first.source_id, "recipe_101")
        self.assertIn("Title: Avocado Black Bean Rice Bowl", first.document_text)
        self.assertIn("Body:", first.document_text)
        self.assertEqual(first.metadata["dish"], "Fuel Bowl")
        self.assertEqual(first.metadata["stage"], "Post-game snack")
        self.assertEqual(first.metadata["nid"], "101")
        self.assertEqual(json.loads(first.metadata["dish_terms"]), ["Fuel Bowl"])

    def test_load_uses_collection_when_provided(self) -> None:
        fake_collection = FakeCollection()
        loader = RecipeLoader(csv_path=FIXTURE_CSV, collection=fake_collection)
        records = loader.load()

        self.assertEqual(len(fake_collection.upserts), 1)
        ids, documents, metadatas = fake_collection.upserts[0]
        self.assertEqual(ids[:2], ["recipe_101", "recipe_102"])
        self.assertEqual(len(ids), len(documents))
        self.assertEqual(len(ids), len(metadatas))
        self.assertEqual(len(records), len(ids))
        self.assertTrue(ids[2].startswith("recipe_"))
        self.assertNotEqual(ids[2], "recipe_101")

    def test_metadata_values_are_scalar(self) -> None:
        loader = RecipeLoader(csv_path=FIXTURE_CSV)
        record = loader.load_records()[0]

        for value in record.metadata.values():
            self.assertFalse(isinstance(value, (list, dict)))


class NormalizeRecipeRowTests(unittest.TestCase):
    def test_normalize_recipe_row_outputs_expected_schema(self) -> None:
        row = {
            "title": "English Breakfast",
            "body": "<p>Hearty plate with eggs & beans.</p>",
            "dish": "Breakfast;Hot",
            "stage": "Published",
            "source_url": "https://example.com/english-breakfast",
            "nid": "200",
            "food_pics": "https://site/img1.jpg|/images/img2.png",
            "source_csv": "backdrop_export_march.csv",
            "dish_tags": "savory, classic",
        }

        recipe = normalize_recipe_row(row)

        self.assertEqual(recipe.source_id, "recipe_200")
        self.assertEqual(recipe.title, "English Breakfast")
        self.assertEqual(recipe.nid, "200")
        self.assertEqual(recipe.dish_terms, ["Breakfast", "Hot"])
        self.assertEqual(recipe.stage_tags, ["Published"])
        self.assertEqual(recipe.food_pics_raw, "https://site/img1.jpg|/images/img2.png")
        self.assertEqual(
            recipe.image_urls, ["https://site/img1.jpg", "/images/img2.png"]
        )
        self.assertTrue(recipe.has_images)
        self.assertEqual(recipe.image_count, 2)
        self.assertIn("source_csv", recipe.extra_fields)
        self.assertEqual(recipe.extra_fields["source_csv"], "backdrop_export_march.csv")
        self.assertNotIn("food_pics", recipe.extra_fields)

    def test_recipe_to_record_merges_extra_fields(self) -> None:
        row = {
            "title": "English Breakfast",
            "body": "Eggs, beans, toast.",
            "dish": "Breakfast",
            "stage": "Published",
            "source_url": "https://example.com/english-breakfast",
            "nid": "210",
            "food_pics": "https://site/img1.jpg",
            "source_csv": "snapshot.csv",
        }

        recipe = normalize_recipe_row(row)
        record = recipe_to_record(recipe)

        self.assertIn("Title: English Breakfast", record.document_text)
        self.assertEqual(record.metadata["primary_image_url"], "https://site/img1.jpg")
        self.assertEqual(record.metadata["image_count"], 1)
        self.assertEqual(record.metadata["source_csv"], "snapshot.csv")
        self.assertEqual(record.metadata["source_id"], "recipe_210")


class RecipeLoaderImageParsingTests(unittest.TestCase):
    def _metadata_for_pics(self, pics_value: str) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "images.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "nid",
                        "title",
                        "body",
                        "dish",
                        "stage",
                        "source_url",
                        "food_pics",
                    ]
                )
                writer.writerow(
                    [
                        "501",
                        "Image Test",
                        "Body",
                        "Dish",
                        "Stage",
                        "https://example.com",
                        pics_value,
                    ]
                )

            loader = RecipeLoader(csv_path=csv_path)
            record = loader.load_records()[0]
            return record.metadata

    def test_image_metadata_empty(self) -> None:
        metadata = self._metadata_for_pics("")

        self.assertEqual(json.loads(metadata["image_urls"]), [])
        self.assertEqual(metadata["image_count"], 0)
        self.assertFalse(metadata["has_images"])
        self.assertEqual(metadata["primary_image_url"], "")
        self.assertEqual(metadata["food_pics_raw"], "")

    def test_image_metadata_single_url(self) -> None:
        metadata = self._metadata_for_pics(" https://site/img1.jpg ")

        self.assertEqual(
            json.loads(metadata["image_urls"]), ["https://site/img1.jpg"]
        )
        self.assertEqual(metadata["image_count"], 1)
        self.assertTrue(metadata["has_images"])
        self.assertEqual(metadata["primary_image_url"], "https://site/img1.jpg")

    def test_image_metadata_multiple_urls(self) -> None:
        metadata = self._metadata_for_pics(
            "https://site/img1.jpg| https://site/img2.png |https://site/img3.webp"
        )

        self.assertEqual(
            json.loads(metadata["image_urls"]),
            [
                "https://site/img1.jpg",
                "https://site/img2.png",
                "https://site/img3.webp",
            ],
        )
        self.assertEqual(metadata["image_count"], 3)
        self.assertEqual(metadata["primary_image_url"], "https://site/img1.jpg")

    def test_image_metadata_filters_malformed_entries(self) -> None:
        metadata = self._metadata_for_pics(
            "not-a-url|https://site/photo.jpg?size=large|invalid"
        )

        self.assertEqual(
            json.loads(metadata["image_urls"]), ["https://site/photo.jpg?size=large"]
        )
        self.assertEqual(metadata["image_count"], 1)

    def test_image_metadata_accepts_relative_paths(self) -> None:
        metadata = self._metadata_for_pics("images/team-photo.JPG")

        self.assertEqual(
            json.loads(metadata["image_urls"]), ["images/team-photo.JPG"]
        )
        self.assertTrue(metadata["has_images"])


if __name__ == "__main__":
    unittest.main()
