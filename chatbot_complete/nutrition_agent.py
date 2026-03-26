import json
import sys
from pathlib import Path

from agents import (
    Agent,
    function_tool,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nutrition_lookup import NutritionLookup

nutrition_lookup = NutritionLookup()


@function_tool
def nutrition_lookup_tool(query: str) -> str:
    """
    Tool function that looks up nutrition information for a specific ingredient.

    Args:
        query: The food item to look up.

    Returns:
        JSON-formatted nutrition information or an error string.
    """
    result = nutrition_lookup.lookup(query)
    if not result:
        return f"No nutrition information found for: {query}"

    return json.dumps(result.to_dict(), indent=2)


nutrition_agent = Agent(
    name="Nutrition Assistant",
    instructions="""
    You are a helpful nutrition assistant giving out nutrition information (calories, macros, fiber).
    You give concise answers.
    If you need to look up nutrition information, use the nutrition_lookup_tool.
    """,
    tools=[nutrition_lookup_tool],
)
