from langchain_core.messages.ai import AIMessage
from agents.state import OrderState, Cart
from agents.prompts.system_prompt import SYSTEM_INSTRUCTION, WELCOME_MSG
from langchain.chat_models import init_chat_model
from agents.tools.cart import get_menu, get_cart, add_cart, remove_from_cart, place_order, confirm_order


def chatbot(state: OrderState) -> OrderState:
    """The chatbot itself. A wrapper around the model's own chat interface."""

    model = init_chat_model("gemini-2.5-flash", model_provider="google_genai")
    tools = [get_menu, get_cart, add_cart,
             remove_from_cart, place_order, confirm_order]

    # bind these tools to the LLM
    model_with_tools = model.bind_tools(tools)

    # format system instruction
    formatted_system_instruction = (
        SYSTEM_INSTRUCTION[0], SYSTEM_INSTRUCTION[1].format(restaurant_name=state["restaurant_name"]))
    formatted_welcome_msg = WELCOME_MSG.format(
        restaurant_name=state["restaurant_name"])

    if state["messages"]:
        # If there are messages, continue the conversation with the model.
        new_output = model_with_tools.invoke(
            [formatted_system_instruction] + state["messages"])
    else:
        # If there are no messages, start with the welcome message.
        new_output = AIMessage(content=formatted_welcome_msg)

    # Initialize cart as Cart model if not present or if it's an empty list
    current_cart = state.get("cart")
    if current_cart is None or current_cart == []:
        current_cart = Cart(items=[])

    return {
        "messages": state.get("messages", []) + [new_output],
        "cart": current_cart,
        "orderId": state.get("orderId"),
        "finished": state.get("finished", False)
    }
