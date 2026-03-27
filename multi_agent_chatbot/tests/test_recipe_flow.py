import json
import unittest
from pathlib import Path

from effective_recipe import build_effective_recipe


class RecipeFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        path = Path(__file__).resolve().parents[2] / "rag_setup" / "recipes_normalized.jsonl"
        with path.open() as handle:
            first_line = next(handle)
        base_row = json.loads(first_line)
        self.base_recipe = {
            "id": base_row.get("raw_checksum"),
            "title": base_row.get("title"),
            "servings": base_row.get("servings", 2),
            "ingredients": [
                {"name": base_row.get("title"), "quantity": 1, "unit": "serving"}
            ],
        }

    def test_effective_recipe_no_overrides(self) -> None:
        effective = build_effective_recipe(self.base_recipe)
        self.assertEqual(effective["ingredients"], self.base_recipe["ingredients"])

    def test_effective_recipe_with_overrides(self) -> None:
        overrides = {
            "extra": {
                "action": "add",
                "ingredient": {"name": "extra ingredient", "quantity": 10, "unit": "g"},
            }
        }
        effective = build_effective_recipe(self.base_recipe, overrides)
        names = [ing["name"] for ing in effective["ingredients"]]
        self.assertIn("extra ingredient", names)


if __name__ == "__main__":
    unittest.main()
