import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from conversation_state import apply_command, ensure_state, parse_command
from recipe_catalog import list_recipes, get_recipe, DEFAULT_RECIPE_ID


class ConversationStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = ensure_state({})
        recipes = list_recipes()
        if not recipes:
            self.fail("Runtime recipe catalog is empty; cannot run tests.")
        self.primary_recipe = get_recipe(DEFAULT_RECIPE_ID)
        remaining = [r for r in recipes if r["id"] != self.primary_recipe["id"]]
        self.secondary_recipe = remaining[0] if remaining else self.primary_recipe
        self.primary_ingredient = self.primary_recipe["ingredients"][0]

    def test_parse_commands(self) -> None:
        self.assertEqual(parse_command("add arugula")["type"], "add")
        self.assertEqual(parse_command("remove olives")["type"], "remove")
        use_cmd = parse_command("use 150 g chickpeas")
        self.assertEqual(use_cmd["type"], "update_amount")
        self.assertEqual(use_cmd["amount"], 150.0)
        self.assertEqual(use_cmd["unit"], "g")
        servings_cmd = parse_command("make it for 2")
        self.assertEqual(servings_cmd["type"], "servings")
        self.assertEqual(servings_cmd["servings"], 2.0)
        self.assertEqual(parse_command("reset changes")["type"], "reset")

    def test_apply_add_and_update(self) -> None:
        add_cmd = {"type": "add", "ingredient": "pine nuts"}
        result = apply_command(self.state, add_cmd)
        self.assertIn("pine nuts", self.state["ingredient_overrides"])
        self.assertIn(
            "pine nuts",
            [ing["name"] for ing in result["effective_recipe"]["ingredients"]],
        )
        self.assertIn("nutrition_input", result)
        self.assertEqual(result["nutrition_input"]["ingredient_source"], "current")
        self.assertIn(
            "pine nuts", result["nutrition_input"]["ingredient_lines"]
        )
        self.assertIsInstance(
            result["nutrition_input"]["ingredient_lines_excluded"], list
        )

        base = apply_command(self.state, {"type": "reset"})
        self.assertEqual(base["nutrition_input"]["ingredient_source"], "raw")
        target_name = self.primary_ingredient["name"]
        new_amount = (self.primary_ingredient.get("quantity") or 1) * 2
        update_cmd = {
            "type": "update_amount",
            "ingredient": target_name,
            "amount": new_amount,
        }
        if self.primary_ingredient.get("unit"):
            update_cmd["unit"] = self.primary_ingredient["unit"]
        updated = apply_command(self.state, update_cmd)
        self.assertEqual(updated["nutrition_input"]["ingredient_source"], "current")
        formatted_amount = str(new_amount).rstrip("0").rstrip(".")
        current_lines = self.state.get("ingredient_lines_current") or []
        self.assertTrue(
            any(
                target_name.lower() in line.lower() and formatted_amount in line
                for line in current_lines
            )
        )

    def test_servings_and_reset(self) -> None:
        base = apply_command(self.state, {"type": "reset"})
        base_lines = list(base["nutrition_input"]["ingredient_lines"])
        servings_cmd = {"type": "servings", "servings": 2}
        result = apply_command(self.state, servings_cmd)
        self.assertEqual(self.state["servings_override"], 2)
        self.assertEqual(result["nutrition"]["servings"], 2)
        self.assertEqual(result["nutrition_input"]["ingredient_source"], "current")
        self.assertNotEqual(
            base_lines, result["nutrition_input"]["ingredient_lines"]
        )

        reset_cmd = {"type": "reset"}
        reset_result = apply_command(self.state, reset_cmd)
        self.assertEqual(self.state["ingredient_overrides"], {})
        self.assertIsNone(self.state["servings_override"])
        self.assertEqual(reset_result["nutrition_input"]["ingredient_source"], "raw")

    def test_select_recipe_command(self) -> None:
        target_title = self.secondary_recipe["title"]
        cmd = parse_command(f"Use recipe: {target_title}")
        self.assertIsNotNone(cmd)
        assert cmd is not None
        self.assertEqual(cmd["type"], "select_recipe")
        result = apply_command(self.state, cmd)
        self.assertEqual(self.state["working_recipe_id"], self.secondary_recipe["id"])
        self.assertEqual(result["effective_recipe"]["title"], target_title)
        # Switching recipes resets overrides and uses raw ingredient lines
        self.assertEqual(result["nutrition_input"]["ingredient_source"], "raw")


if __name__ == "__main__":
    unittest.main()
