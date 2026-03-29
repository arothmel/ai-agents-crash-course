import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nutrition_lookup import NutritionLookup

EUROFIR_CSV = REPO_ROOT / "data" / "eurofir_mediterranean.csv"


class NutritionLookupHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lookup = NutritionLookup(csv_path=EUROFIR_CSV)

    def test_lookup_known_and_unknown_ingredients(self) -> None:
        known_ingredients = ["chickpeas", "lentils", "tomatoes"]
        for ingredient in known_ingredients:
            with self.subTest(ingredient=ingredient):
                result = self.lookup.lookup(ingredient)
                self.assertIsNotNone(result)
                assert result  # help type-checkers
                self.assertIn(ingredient.split()[0], result["ingredient"])

        self.assertIsNone(self.lookup.lookup("anchovies"))


class NutritionToolTests(unittest.TestCase):
    def test_tool_returns_expected_payload(self) -> None:
        response = json.dumps(NutritionLookup().lookup("chickpeas"), indent=2)
        try:
            payload = json.loads(response)
        except json.JSONDecodeError as exc:  # pragma: no cover - fails loudly
            self.fail(f"Tool response is not valid JSON: {exc}")

        expected = {
            "query": "chickpeas",
            "ingredient": "chickpeas cooked",
            "per_100g": {
                "kcal": 164.0,
                "protein_g": 8.9,
                "carbs_g": 27.4,
                "fat_g": 2.6,
                "fiber_g": 7.6,
            },
            "signals": ["protein_source", "fiber_source"],
            "source": "eurofir_mediterranean",
        }

        self.assertEqual(payload, expected)


if __name__ == "__main__":
    unittest.main()
