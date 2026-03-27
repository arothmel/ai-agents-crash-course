import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from conversation_state import apply_command, ensure_state, parse_command


class ConversationStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = ensure_state({})

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

        base = apply_command(self.state, {"type": "reset"})
        base_kcal = base["nutrition"]["totals"]["kcal"]
        update_cmd = {
            "type": "update_amount",
            "ingredient": "chickpeas",
            "amount": 200,
            "unit": "g",
        }
        updated = apply_command(self.state, update_cmd)
        self.assertGreater(
            updated["nutrition"]["totals"]["kcal"], base_kcal,
        )

    def test_servings_and_reset(self) -> None:
        servings_cmd = {"type": "servings", "servings": 2}
        result = apply_command(self.state, servings_cmd)
        self.assertEqual(self.state["servings_override"], 2)
        self.assertEqual(result["nutrition"]["servings"], 2)

        reset_cmd = {"type": "reset"}
        apply_command(self.state, reset_cmd)
        self.assertEqual(self.state["ingredient_overrides"], {})
        self.assertIsNone(self.state["servings_override"])


if __name__ == "__main__":
    unittest.main()
