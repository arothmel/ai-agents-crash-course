import os

import chainlit as cl
import dotenv
from agents import InputGuardrailTripwireTriggered, Runner, SQLiteSession
from nutrition_agent import exa_search_mcp, nutrition_agent
from openai.types.responses import ResponseTextDeltaEvent

dotenv.load_dotenv()


@cl.on_chat_start
async def on_chat_start():
    session = SQLiteSession("conversation_history")
    cl.user_session.set("agent_session", session)
    # This is the only change in this file compared to the chatbot/agentic_chatbot.py file
    await exa_search_mcp.connect()


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

    msg = cl.Message(content="")

    try:
        result = Runner.run_streamed(
            nutrition_agent,
            message.content,
            session=session,
        )

        async for event in result.stream_events():
            # Stream final message text to screen
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
        await msg.update()

    except InputGuardrailTripwireTriggered:
        msg.content = "Sorry, I can only answer food-related questions."
        await msg.update()

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
