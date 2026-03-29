import os
from dataclasses import dataclass
from enum import Enum

import chainlit as cl
import dotenv
import openai

dotenv.load_dotenv()

from agents import InputGuardrailTripwireTriggered, Runner, SQLiteSession
from conversation_state import apply_command, ensure_state, parse_command
from effective_recipe import build_effective_recipe
from recipe_catalog import get_recipe, list_recipes
from nutrition_agent import exa_search_mcp, nutrition_agent
from openai.types.responses import ResponseTextDeltaEvent


WORKING_STATE_KEY = "working_state"

STARTER_ACTIONS = [
    ("Show ingredients", "Show me the ingredients for this recipe."),
    ("Estimate calories", "Estimate the calories for this recipe."),
    ("Suggest substitutions", "Suggest ingredient substitutions."),
    ("Herbs/spices excluded", "Which herbs or spices were excluded?"),
    ("Unresolved ingredients", "Which ingredients are unresolved?"),
]


class InteractionMode(Enum):
    LOOKUP = "lookup"
    INTERPRET = "interpret"


@dataclass
class ParsedInteraction:
    mode: InteractionMode


def _normalize_ingredient(text: str) -> str:
    return text.strip().lower()


def _parse_interaction(text: str) -> ParsedInteraction:
    lowered = text.strip().lower()
    if not lowered:
        return ParsedInteraction(mode=InteractionMode.LOOKUP)

    if "ingredient" in lowered and ("what" in lowered or "current" in lowered):
        return ParsedInteraction(mode=InteractionMode.INTERPRET)

    return ParsedInteraction(mode=InteractionMode.LOOKUP)


def _extract_command_and_message(text: str) -> tuple[dict | None, str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None, ""
    first_line = lines[0]
    command = parse_command(first_line)
    if not command:
        return None, text
    remaining = "\n".join(lines[1:]).strip()
    return command, remaining


def _get_working_state() -> dict:
    state = cl.user_session.get(WORKING_STATE_KEY)
    state = ensure_state(state)
    cl.user_session.set(WORKING_STATE_KEY, state)
    return state


def _format_working_ingredients(state: dict) -> str:
    items = state.get("working_ingredients", [])
    if not items:
        return "(no ingredients yet)"
    return ", ".join(item.title() for item in items)


async def _prompt_recipe_selection(session: SQLiteSession) -> None:
    recipes = list_recipes()
    if not recipes:
        return
    actions = [
        cl.Action(
            name="select_recipe",
            label=recipe.get("title") or "Untitled",
            payload={"id": recipe["id"]},
        )
        for recipe in recipes
    ]
    await cl.Message(
        content="Choose a recipe to get started:",
        actions=actions,
    ).send()


def _summarize_effective_recipe(state: dict) -> tuple[str, dict] | tuple[str, None]:
    base = get_recipe(state.get("working_recipe_id"))
    effective = build_effective_recipe(
        base,
        state.get("ingredient_overrides"),
        state.get("servings_override"),
    )
    servings = effective.get("servings")
    ingredient_lines = []
    for ing in effective.get("ingredients", []):
        name = ing.get("name", "Unknown").title()
        qty = ing.get("quantity") or ing.get("amount")
        unit = ing.get("unit")
        if qty is not None:
            if unit:
                ingredient_lines.append(f"{name} ({qty} {unit})")
            else:
                ingredient_lines.append(f"{name} ({qty})")
        else:
            ingredient_lines.append(name)
    summary = (
        f"Working recipe: {effective.get('title', 'N/A')} (servings: {servings}). "
        f"Use exactly these ingredient quantities: {', '.join(ingredient_lines)}. "
        "If asked about nutrition, rely on these amounts (do not ask the user). "
    )
    return summary, effective


def _format_nutrition_summary(result: dict) -> str:
    effective = result["effective_recipe"]
    nutrition = result["nutrition"]
    status = result.get("status")
    lines: list[str] = []
    if status:
        lines.append(status)
    lines.append(
        f"Recipe: {effective.get('title', 'Working Recipe')} (servings: {nutrition['servings']})"
    )
    ingredients = ", ".join(ing["name"].title() for ing in effective.get("ingredients", []))
    lines.append(f"Ingredients: {ingredients or '(none)'}")

    labels = {
        "kcal": "Calories",
        "protein_g": "Protein (g)",
        "carbs_g": "Carbs (g)",
        "fat_g": "Fat (g)",
        "fiber_g": "Fiber (g)",
    }

    totals = nutrition["totals"]
    per_serving = nutrition["per_serving"]
    total_line = ", ".join(f"{labels[key]}: {totals[key]:.1f}" for key in labels)
    per_serving_line = ", ".join(f"{labels[key]}: {per_serving[key]:.1f}" for key in labels)
    lines.append(f"Batch totals -> {total_line}")
    lines.append(f"Per serving -> {per_serving_line}")

    missing = nutrition.get("missing") or []
    if missing:
        lines.append(
            "Missing nutrition data for: " + ", ".join(name.title() for name in missing)
        )

    return "\n".join(lines)


def _augment_message(original_message: str, state: dict) -> str:
    summary, _ = _summarize_effective_recipe(state)
    context = summary
    return context + original_message


async def _handle_user_message(message_text: str, session: SQLiteSession) -> None:
    msg = cl.Message(content="")
    try:
        state = _get_working_state()
        command, remaining_message = _extract_command_and_message(message_text)
        if command:
            result = apply_command(state, command)
            cl.user_session.set(WORKING_STATE_KEY, state)
            msg.content = _format_nutrition_summary(result)
            await msg.send()
            if command.get("type") == "select_recipe":
                await _send_conversation_starters()
            if remaining_message:
                await _handle_user_message(remaining_message, session)
            return

        parsed = _parse_interaction(message_text)

        if parsed.mode == InteractionMode.INTERPRET:
            msg.content = f"Current working ingredients: {_format_working_ingredients(state)}"
            await msg.send()
            return

        transformed_message = _augment_message(message_text, state)

        try:
            result = Runner.run_streamed(
                nutrition_agent,
                transformed_message,
                session=session,
            )

            async for event in result.stream_events():
                if event.type == "raw_response_event" and isinstance(
                    event.data, ResponseTextDeltaEvent
                ):
                    await msg.stream_token(token=event.data.delta)
                    print(event.data.delta, end="", flush=True)

                elif (
                    event.type == "raw_response_event"
                    and hasattr(event.data, "item")
                    and hasattr(event.data.item, "type")
                    and event.data.item.type == "function_call"
                    and len(event.data.item.arguments) > 0
                ):
                    async with cl.Step(name=event.data.item.name, type="tool") as step:
                        step.input = event.data.item.arguments
                        print(
                            f"\nTool call: {event.data.item.name} "
                            f"with args: {event.data.item.arguments}"
                        )

            msg.content = croissant_upsell(msg.content)
            await msg.send()

        except openai.APIError as exc:  # Graceful failure with request id
            request_id = getattr(exc, "request_id", None)
            error_message = getattr(exc, "message", str(exc))
            msg.content = (
                "OpenAI streaming error. Please retry. "
                f"Request ID: {request_id or 'unknown'}. Error: {error_message}"
            )
            await msg.send()

        except InputGuardrailTripwireTriggered:
            msg.content = (
                "This question may not be about food. Please rephrase it with food-specific"
                " context."
            )
            await msg.send()

    except Exception as e:  # pragma: no cover - safety net
        msg.content = f"Unexpected error: {e}"
        await msg.send()
        raise


async def _send_conversation_starters() -> None:
    actions = [
        cl.Action(name="starter_action", label=label, payload={"prompt": prompt})
        for label, prompt in STARTER_ACTIONS
    ]
    await cl.Message(
        content="Conversation starters:",
        actions=actions,
    ).send()


@cl.on_chat_start
async def on_chat_start():
    session = SQLiteSession("conversation_history")
    cl.user_session.set("agent_session", session)
    # This is the only change in this file compared to the chatbot/agentic_chatbot.py file
    if exa_search_mcp:
        await exa_search_mcp.connect()
    ensure_state(cl.user_session.get(WORKING_STATE_KEY))
    tip = (
        "ℹ️ To analyze a specific recipe, start your message with `Use recipe: Exact Recipe Title` "
        "(for example, `Use recipe: Black Eyed Peas Recipe (Greek-Style)`)."
    )
    await cl.Message(content=tip).send()
    await _prompt_recipe_selection(session)


def croissant_upsell(text: str) -> str:
    french_triggers = [
        "france",
        "french",
        "paris",
        "niçoise",
        "provence",
        "dijon",
        "bordeaux",
        "baguette",
    ]

    if any(word in text.lower() for word in french_triggers):
        text += "\n\n🥐 For only 120 calories more, may we interest you in a croissant with that?"

    return text


@cl.on_message
async def on_message(message: cl.Message):
    session = cl.user_session.get("agent_session")
    if session is None:
        session = SQLiteSession("conversation_history")
        cl.user_session.set("agent_session", session)
    await _handle_user_message(message.content, session)


@cl.action_callback("starter_action")
async def on_starter_action(action: cl.Action):
    session = cl.user_session.get("agent_session")
    if session is None:
        session = SQLiteSession("conversation_history")
        cl.user_session.set("agent_session", session)
    prompt = None
    if isinstance(action.payload, dict):
        prompt = action.payload.get("prompt")
    if not prompt:
        prompt = action.value
    if not prompt:
        await cl.Message(content="No prompt available for this action.").send()
        return
    await _handle_user_message(prompt, session)


@cl.action_callback("select_recipe")
async def on_select_recipe(action: cl.Action):
    session = cl.user_session.get("agent_session")
    if session is None:
        session = SQLiteSession("conversation_history")
        cl.user_session.set("agent_session", session)
    recipes = list_recipes()
    selected_id = None
    if isinstance(action.payload, dict):
        selected_id = action.payload.get("id")
    if not selected_id and action.value:
        selected_id = action.value
    selected = next((recipe for recipe in recipes if recipe["id"] == selected_id), None)
    if not selected:
        selected = next(
            (
                recipe
                for recipe in recipes
                if (recipe.get("title") or "").strip() == (action.value or "")
            ),
            None,
        )
    if not selected:
        await cl.Message(content="Recipe not found in catalog.").send()
        return
    await _handle_user_message(f"Use recipe: {selected.get('title')}", session)

@cl.password_auth_callback
def auth_callback(username: str, password: str):
    if (username, password) == (
        os.getenv("CHAINLIT_USERNAME"),
        os.getenv("CHAINLIT_PASSWORD"),
    ):
        return cl.User(
            identifier="Student",
            metadata={"role": "student", "provider": "credentials"},
        )
    else:
        return None
