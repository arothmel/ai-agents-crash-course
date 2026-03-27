import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from effective_recipe import build_effective_recipe


BASE_RECIPE = {
    "id": "recipe_101",
    "title": "Chickpea Bowl",
    "servings": 4,
    "ingredients": [
        {"name": "chickpeas", "quantity": 100, "unit": "g"},
        {"name": "arugula", "quantity": 30, "unit": "g"},
        {"name": "olive oil", "quantity": 10, "unit": "ml"},
    ],
}


def _override(action, **kwargs):
    entry = {"action": action}
    entry.update(kwargs)
    return entry


class EffectiveRecipeTests(unittest.TestCase):
    def test_add_remove_update_swap_and_servings(self) -> None:
        overrides = {
            "add_pine_nuts": _override(
                "add", ingredient={"name": "pine nuts", "quantity": 15, "unit": "g"}
            ),
            "remove_arugula": _override("remove", ingredient={"name": "arugula"}),
            "update_chickpeas": _override(
                "update", ingredient={"name": "chickpeas"}, amount=150
            ),
            "swap_oil": _override(
                "swap",
                ingredient={"name": "olive oil"},
                replacement={"name": "avocado oil", "quantity": 12, "unit": "ml"},
            ),
        }

        effective = build_effective_recipe(BASE_RECIPE, overrides, servings_override=2)

        # Verify base recipe untouched
        self.assertEqual(BASE_RECIPE["ingredients"][0]["quantity"], 100)
        self.assertEqual(BASE_RECIPE["servings"], 4)

        names = {ing["name"] for ing in effective["ingredients"]}
        self.assertIn("pine nuts", names)
        self.assertNotIn("arugula", names)
        self.assertIn("avocado oil", names)

        chickpeas = next(ing for ing in effective["ingredients"] if ing["name"] == "chickpeas")
        # scaled to servings_override=2 (half of base 4) after updating to 150
        self.assertEqual(chickpeas["quantity"], 75.0)

        pine_nuts = next(ing for ing in effective["ingredients"] if ing["name"] == "pine nuts")
        self.assertEqual(pine_nuts["quantity"], 7.5)

        self.assertEqual(effective["servings"], 2)
        self.assertEqual(effective["servings_source"], "override")

    def test_no_overrides_returns_copy(self) -> None:
        effective = build_effective_recipe(BASE_RECIPE)
        self.assertIsNot(effective, BASE_RECIPE)
        self.assertEqual(effective["ingredients"], BASE_RECIPE["ingredients"])
        self.assertEqual(effective["servings"], BASE_RECIPE["servings"])
        self.assertEqual(effective["servings_source"], "base")


if __name__ == "__main__":
    unittest.main()
