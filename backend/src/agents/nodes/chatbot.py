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

from src.db.database import SessionLocal
from src.services.langgraph_cart import (
    load_langgraph_cart,
    persist_langgraph_cart,
)


_model = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash-lite",
    google_api_key=config.GOOGLE_API_KEY,
    temperature=0,
    max_retries=1,
)


_tools = [
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

_model_with_tools = _model.bind_tools(_tools)


def _load_persistent_cart(state: OrderState) -> Cart:
    """Load the authenticated user's persistent cart."""

    user_id = state.get("user_id")

    if user_id is None:
        current_cart = state.get("cart")

        if current_cart is None or current_cart == []:
            return Cart(items=[])

        return current_cart

    with SessionLocal() as db:
        return load_langgraph_cart(
            db,
            user_id=user_id,
            restaurant_name=state["restaurant_name"],
            subdomain=state["subdomain"],
        )


def _persist_cart(state: OrderState, cart: Cart) -> None:
    """Persist the authenticated LangGraph cart."""

    user_id = state.get("user_id")

    if user_id is None:
        return

    with SessionLocal() as db:
        persist_langgraph_cart(
            db,
            user_id=user_id,
            restaurant_name=state["restaurant_name"],
            subdomain=state["subdomain"],
            cart=cart,
        )


def chatbot(state: OrderState) -> OrderState:
    """The chatbot itself. A wrapper around Gemini."""

    current_cart = state.get("cart")

    # On the first authenticated turn, hydrate LangGraph from the
    # persistent database cart. On subsequent turns, the graph state
    # already contains the current cart produced by the tools.
    if current_cart is None:
        current_cart = _load_persistent_cart(state)

    if current_cart == []:
        current_cart = Cart(items=[])

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
        new_output = _model_with_tools.invoke(
            [formatted_system_instruction] + state["messages"]
        )
    else:
        new_output = AIMessage(content=formatted_welcome_msg)

    # Persist every authenticated cart state produced by LangGraph.
    # This covers add, remove, clear and successful checkout.
    _persist_cart(state, current_cart)

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
        "user_id": state.get("user_id"),
        "finished": state.get("finished", False),
    }
