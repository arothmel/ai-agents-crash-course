import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from effective_recipe import build_effective_recipe
from nutrition_calculator import NutritionCalculator

BASE_RECIPE = {
    "id": "recipe_101",
    "title": "Chickpea Bowl",
    "servings": 4,
    "ingredients": [
        {"name": "chickpeas", "quantity": 100, "unit": "g"},
        {"name": "arugula", "quantity": 30, "unit": "g"},
    ],
}


class NutritionCalculatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calculator = NutritionCalculator()

    def test_base_recipe_totals(self) -> None:
        effective = build_effective_recipe(BASE_RECIPE)
        results = self.calculator.calculate(effective)

        self.assertAlmostEqual(results["totals"]["kcal"], 171.5, places=1)
        self.assertAlmostEqual(results["totals"]["protein_g"], 9.68, places=2)
        self.assertAlmostEqual(results["per_serving"]["kcal"], 42.875, places=3)

    def test_amount_override(self) -> None:
        overrides = {
            "double_chickpeas": {
                "action": "update",
                "ingredient": {"name": "chickpeas"},
                "amount": 200,
            }
        }
        effective = build_effective_recipe(BASE_RECIPE, overrides)
        results = self.calculator.calculate(effective)

        self.assertAlmostEqual(results["totals"]["kcal"], 335.5, places=1)
        self.assertAlmostEqual(results["totals"]["protein_g"], 18.58, places=2)

    def test_add_and_remove(self) -> None:
        overrides = {
            "add_pine_nuts": {
                "action": "add",
                "ingredient": {"name": "pine nuts", "quantity": 10, "unit": "g"},
            },
            "remove_arugula": {"action": "remove", "ingredient": {"name": "arugula"}},
        }
        effective = build_effective_recipe(BASE_RECIPE, overrides)
        results = self.calculator.calculate(effective)

        # pine nuts 10g -> 67.3 kcal added, arugula removed
        self.assertAlmostEqual(results["totals"]["kcal"], 231.3, places=1)
        self.assertAlmostEqual(results["totals"]["fat_g"], 9.44, places=2)

    def test_servings_override_scales_per_serving(self) -> None:
        effective = build_effective_recipe(BASE_RECIPE, servings_override=2)
        results = self.calculator.calculate(effective)

        self.assertEqual(results["servings"], 2)
        self.assertAlmostEqual(results["per_serving"]["kcal"], 42.875, places=3)


if __name__ == "__main__":
    unittest.main()
