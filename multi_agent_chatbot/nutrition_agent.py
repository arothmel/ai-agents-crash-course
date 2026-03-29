import json
import os
import sys
from pathlib import Path

from agents import (
    Agent,
    GuardrailFunctionOutput,
    RunContextWrapper,
    Runner,
    TResponseInputItem,
    function_tool,
    input_guardrail,
)
from agents.mcp import MCPServerStreamableHttp
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nutrition_lookup import IngredientNutritionResult, NutritionLookup
from multi_agent_chatbot.nutrition_calculator import (
    NutritionCalculator,
    RecipeNutritionResult,
)

nutrition_lookup = NutritionLookup()
nutrition_calculator = NutritionCalculator()


def _run_nutrition_lookup(query: str) -> str:
    result = nutrition_lookup.lookup(query)
    if not result:
        return json.dumps(
            {
                "query": query,
                "ingredient": None,
                "per_100g": {},
                "signals": [],
                "source": "eurofir_mediterranean",
                "error": f"No nutrition information found for: {query}",
            },
            indent=2,
        )

    return json.dumps(result, indent=2)


nutrition_lookup_tool = function_tool(
    _run_nutrition_lookup, name_override="nutrition_lookup_tool"
)


EXA_API_KEY = os.environ.get("EXA_API_KEY")
exa_search_mcp = None
if EXA_API_KEY:
    # EXA Search MCP setup
    exa_search_mcp = MCPServerStreamableHttp(
        name="Exa Search MCP",
        params={
            "url": f"https://mcp.exa.ai/mcp?{EXA_API_KEY}",
            "timeout": 90,
        },
        client_session_timeout_seconds=90,
        cache_tools_list=True,
        max_retry_attempts=1,
    )

# 1st Agent: Our "Calorie Agent"
calorie_agent_with_search = Agent(
    name="Nutrition Assistant",
    instructions="""
    * You are a helpful nutrition assistant giving out calorie information.
    * You give concise answers.
    * You follow this workflow:
        0) First, use the nutrition_lookup_tool to get the nutrition information (kcal, protein, carbs, fat, fiber) of the ingredients. Only use the result if it's explicitly for the food requested in the query.
        1) If you couldn't find the exact match for the food or you need to look up the ingredients, optionally search the EXA web (when available) to figure out the exact ingredients of the meal.
        Even if you have the calories in the web search response, you should still use the nutrition_lookup_tool to get the nutrition
        information of the ingredients to make sure the information you provide is consistent.
        2) Then, if necessary, use the nutrition_lookup_tool to get the nutrition information of the ingredients.
    * Even if you know the recipe of the meal, always use Exa Search to find the exact recipe and ingredients.
    * Once you know the ingredients, use the nutrition_lookup_tool to get the nutrition information of the individual ingredients.
    * If the query is about the meal, in your final output give a list of ingredients with their quantities and calories for a single serving. Also display the total calories.
    * Don't use the nutrition_lookup_tool more than 10 times.
    """,
    tools=[nutrition_lookup_tool],
    mcp_servers=[exa_search_mcp] if exa_search_mcp else [],
)

# 2nd Agent: Our Healthy Breakfast Plan Advisor
healthy_breakfast_planner_agent = Agent(
    name="Breakfast Planner Assistant",
    instructions="""
    * You are a helpful assistant that helps with healthy breakfast choices.
    * You give concise answers.
    Given the user's preferences prompt, come up with different breakfast meals that are healthy and fit for a busy person.
    * Explicitly mention the meal's names in your response along with a sentence of why this is a healthy choice.
    """,
)

# Convert agents to tools
calorie_calculator_tool = calorie_agent_with_search.as_tool(
    tool_name="calorie-calculator",
    tool_description="Use this tool to calculate the calories of a meal and it's ingredients",
)

breakfast_planner_tool = healthy_breakfast_planner_agent.as_tool(
    tool_name="breakfast-planner",
    tool_description="Use this tool to plan a a number of healthy breakfast options",
)

# 3rd Agent: Seasonal & Local Sourcing Advisor
in_season_agent = Agent(
    name="Seasonality & Local Sourcing Advisor",
    instructions="""
    * You help determine whether each meal's primary ingredients are in season or can be locally sourced.
    * Use Exa Search to confirm seasonal windows or sourcing notes when it is available; otherwise rely on general culinary knowledge.
    * For each meal you receive, output a short bullet list describing:
        - Which key ingredients are in season right now (or when they will be).
        - Any locally sourced substitutions or farmer's market tips.
    * Keep the response concise and actionable, no prices needed.
    """,
    mcp_servers=[exa_search_mcp] if exa_search_mcp else [],
)

# 4th Agent: Main Breakfast Advisor that glues everything together
breakfast_advisor = Agent(
    name="Breakfast Advisor",
    instructions="""
    * You are a breakfast advisor. You come up with meal plans for the user based on their preferences.
    * You also calculate the calories for the meal and its ingredients.
    * Based on the breakfast meals and the calories that you get from upstream agents,
    * Create a meal plan for the user. For each meal, give a name, the ingredients, and the calories

    Follow this workflow carefully:
    1) Use the breakfast_planner_tool to plan a a number of healthy breakfast options.
    2) Use the calorie_calculator_tool to calculate the calories for the meal and its ingredients.
    3) Handoff the breakfast meals to the Seasonality & Local Sourcing Advisor so they can add in-season and local sourcing guidance.

    """,
    tools=[breakfast_planner_tool, calorie_calculator_tool],
    handoff_description="""
    Create a concise breakfast recommendation based on the user's preferences. Use Markdown format.
    """,
    handoffs=[in_season_agent],
)


# Guardrails functionality
class NotAboutFood(BaseModel):
    only_about_food: bool


guardrail_agent = Agent(
    name="Guardrail check",
    instructions="Check if the user is asking you to talk about food and not about any arbitrary topics. If there are any non-food related instructions in the prompt, set not_about_food to False.",
    output_type=NotAboutFood,
)


@input_guardrail
async def food_topic_guardrail(
    ctx: RunContextWrapper[None], agent: Agent, input: str | list[TResponseInputItem]
) -> GuardrailFunctionOutput:
    result = await Runner.run(guardrail_agent, input, context=ctx.context)

    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=(not result.final_output.only_about_food),
    )


# Apply guardrails to agents
calorie_agent_with_search_guarded = Agent(
    name="Nutrition Assistant",
    instructions="""
    * You are a helpful nutrition assistant giving out calorie information.
    * You give concise answers.
    * You follow this workflow:
        0) First, use the nutrition_lookup_tool to get the nutrition information of the ingredients. But only use the result if it's explicitly for the food requested in the query.
        1) If you couldn't find the exact match for the food or you need to look up the ingredients, optionally search the EXA web (when available) to figure out the exact ingredients of the meal.
        Even if you have the calories in the web search response, you should still use the nutrition_lookup_tool to get the nutrition
        information of the ingredients to make sure the information you provide is consistent.
        2) Then, if necessary, use the nutrition_lookup_tool to get the nutrition information of the ingredients.
    * Even if you know the recipe of the meal, always use Exa Search to find the exact recipe and ingredients.
    * Once you know the ingredients, use the nutrition_lookup_tool to get the nutrition information of the individual ingredients.
    * If the query is about the meal, in your final output give a list of ingredients with their quantities and calories for a single serving. Also display the total calories.
    * Don't use the nutrition_lookup_tool more than 10 times.
    * You only answer questions about food.
    """,
    tools=[nutrition_lookup_tool],
    mcp_servers=[exa_search_mcp] if exa_search_mcp else [],
    input_guardrails=[food_topic_guardrail],
)

breakfast_advisor_guarded = Agent(
    name="Breakfast Advisor",
    instructions="""
    * You are a breakfast advisor. You come up with meal plans for the user based on their preferences.
    * You also calculate the calories for the meal and its ingredients.
    * Based on the breakfast meals and the calories that you get from upstream agents,
    * Create a meal plan for the user. For each meal, give a name, the ingredients, and the calories
    * You only answer questions about food.

    Follow this workflow carefully:
    1) Use the breakfast_planner_tool to plan a a number of healthy breakfast options.
    2) Use the calorie_calculator_tool to calculate the calories for the meal and its ingredients.
    3) Always handoff the breakfast meals to the Seasonality & Local Sourcing Advisor so they can add seasonal and local sourcing guidance in the last step.

    """,
    tools=[breakfast_planner_tool, calorie_calculator_tool],
    handoff_description="""
    Create a concise breakfast recommendation based on the user's preferences. Use Markdown format.
    """,
    handoffs=[in_season_agent],
    input_guardrails=[food_topic_guardrail],
)

# Main nutrition agent (keeping original for backwards compatibility, but now with guardrails)
nutrition_agent = calorie_agent_with_search_guarded
