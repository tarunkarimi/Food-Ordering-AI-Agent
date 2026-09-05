from langchain_core.messages.ai import AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.agents.state import OrderState, Cart
from src.agents.prompts.system_prompt import SYSTEM_INSTRUCTION, WELCOME_MSG
from src.configs.config import config

from src.agents.tools.cart import (
    get_menu,
    get_cart,
    add_cart,
    remove_from_cart,
    clear_cart,
    place_order,
    confirm_order,
)
from src.agents.tools.order import cancel_order, get_order_status


def chatbot(state: OrderState) -> OrderState:
    """The chatbot itself. A wrapper around Gemini."""

    model = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash-lite",
        google_api_key=config.GOOGLE_API_KEY,
    )

    tools = [
        get_menu,
        get_cart,
        add_cart,
        remove_from_cart,
        clear_cart,
        place_order,
        confirm_order,
        get_order_status,
        cancel_order,
    ]

    # Bind tools to Gemini
    model_with_tools = model.bind_tools(tools)

    # Format system instruction
    formatted_system_instruction = (
        SYSTEM_INSTRUCTION[0],
        SYSTEM_INSTRUCTION[1].format(
            restaurant_name=state["restaurant_name"]
        ),
    )

    formatted_welcome_msg = WELCOME_MSG.format(
        restaurant_name=state["restaurant_name"]
    )

    if state["messages"]:
        new_output = model_with_tools.invoke(
            [formatted_system_instruction] + state["messages"]
        )
    else:
        new_output = AIMessage(content=formatted_welcome_msg)

    # Initialize cart if not present
    current_cart = state.get("cart")

    if current_cart is None or current_cart == []:
        current_cart = Cart(items=[])

    return {
        "messages": state.get("messages", []) + [new_output],
        "cart": current_cart,
        "orderId": state.get("orderId"),
        "order_status": state.get("order_status"),
        "order_confirmation_pending": state.get(
            "order_confirmation_pending",
            False,
        ),
        "restaurant_name": state["restaurant_name"],
        "subdomain": state["subdomain"],
        "finished": state.get("finished", False),
    }