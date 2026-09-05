from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json

from src.agents.graph import chatbot_agent_builder
from src.agents.state import Cart, CartItem, CartItemUnit, ItemVariation
from src.agents.tools.cart import (
    _fetch_menu_items,
    _valid_quantity,
    _valid_price,
)


router = APIRouter()

# Build the chatbot agent once when the application starts.
chatbot_agent = chatbot_agent_builder()


class ChatRequest(BaseModel):
    user_message: str
    session_id: Optional[str]
    restaurant_name: str
    subdomain: str


class ManualCartRequest(BaseModel):
    session_id: str
    restaurant_name: str
    subdomain: str
    item_id: Optional[str] = None
    title: Optional[str] = None
    quantity: int = 1
    variation_id: Optional[str] = None


def _session_config(session_id: str):
    return {
        "configurable": {
            "thread_id": session_id.strip()
        }
    }


def _get_existing_cart(session_id: str) -> Cart:
    state = chatbot_agent.get_state(
        _session_config(session_id)
    )

    values = getattr(state, "values", None)

    if not isinstance(values, dict):
        return Cart(items=[])

    cart = values.get("cart")

    if isinstance(cart, Cart):
        return cart

    if isinstance(cart, dict):
        return Cart.model_validate(cart)

    return Cart(items=[])


def _find_menu_item(
    items: list[dict],
    item_id: str,
    title: str,
):
    return next(
        (
            item
            for item in items
            if item.get("id") == item_id
            and item.get("title") == title
        ),
        None,
    )


def _authoritative_unit(
    menu_item: dict,
    item_id: str,
    quantity: int,
    variation_id: Optional[str],
):
    """
    Build a cart unit using the authoritative menu price.

    For items with variations, the variation price becomes
    the cart unit base_price.
    """

    authoritative_price = menu_item.get("base_price")

    if not _valid_price(authoritative_price):
        raise ValueError(
            "That menu item has invalid pricing and cannot be added."
        )

    variations = menu_item.get("variations", [])

    if not isinstance(variations, list):
        raise ValueError(
            "That item has invalid variation data on the current menu."
        )

    selected_variation_id = "no_variant"
    selected_variation = None

    # Default cart price is the menu item's base price.
    cart_unit_price = authoritative_price

    if variations:

        if not variation_id:
            raise ValueError(
                "Please specify a valid variation for this item."
            )

        selected_variation_id = variation_id.strip()

        if not selected_variation_id:
            raise ValueError(
                "A valid variation ID is required."
            )

        menu_variation = next(
            (
                variation
                for variation in variations
                if (
                    isinstance(variation, dict)
                    and variation.get("id") == selected_variation_id
                )
            ),
            None,
        )

        if menu_variation is None:
            raise ValueError(
                "That item variation is not available on the current menu."
            )

        raw_variation_price = menu_variation.get(
            "price",
            authoritative_price,
        )

        try:
            variation_price = float(raw_variation_price)
        except (TypeError, ValueError):
            raise ValueError(
                "That item variation has invalid pricing on the current menu."
            )

        if not _valid_price(variation_price):
            raise ValueError(
                "That item variation has invalid pricing on the current menu."
            )

        selected_variation = ItemVariation(
            id=menu_variation["id"],
            name=str(menu_variation.get("name", "")),
            price=str(raw_variation_price),
        )

        # IMPORTANT:
        # Variation price is the actual cart price.
        cart_unit_price = variation_price

    item_key = f"{item_id}|{selected_variation_id}"

    return CartItemUnit(
        key=item_key,
        quantity=quantity,
        base_price=cart_unit_price,
        variation=selected_variation,
    )


def _add_to_cart(
    current_cart: Cart,
    menu_item: dict,
    quantity: int,
    variation_id: Optional[str],
):
    item_id = menu_item["id"]
    title = menu_item["title"]

    new_unit = _authoritative_unit(
        menu_item,
        item_id,
        quantity,
        variation_id,
    )

    updated_items = []
    item_found = False

    for existing_item in current_cart.items:

        if existing_item.item_id != item_id:
            updated_items.append(existing_item)
            continue

        item_found = True
        unit_found = False
        updated_units = []

        for existing_unit in existing_item.units:

            if existing_unit.key == new_unit.key:
                unit_found = True

                updated_units.append(
                    CartItemUnit(
                        key=existing_unit.key,
                        quantity=(
                            existing_unit.quantity
                            + quantity
                        ),
                        # Use the authoritative current price.
                        base_price=new_unit.base_price,
                        variation=new_unit.variation,
                    )
                )

            else:
                updated_units.append(existing_unit)

        if not unit_found:
            updated_units.append(new_unit)

        updated_items.append(
            CartItem(
                item_id=item_id,
                title=title,
                units=updated_units,
            )
        )

    if not item_found:
        updated_items.append(
            CartItem(
                item_id=item_id,
                title=title,
                units=[new_unit],
            )
        )

    return Cart(items=updated_items)


def _remove_from_cart(
    current_cart: Cart,
    item_id: str,
    title: str,
    quantity: int,
    variation_id: Optional[str],
):
    selected_variation_id = (
        variation_id.strip()
        if variation_id
        else "no_variant"
    )

    if not selected_variation_id:
        raise ValueError(
            "A valid variation ID is required."
        )

    item_key = f"{item_id}|{selected_variation_id}"

    updated_items = []
    item_found = False

    for existing_item in current_cart.items:

        if existing_item.item_id != item_id:
            updated_items.append(existing_item)
            continue

        unit_found = False
        updated_units = []

        for existing_unit in existing_item.units:

            if existing_unit.key != item_key:
                updated_units.append(existing_unit)
                continue

            unit_found = True

            if existing_unit.quantity > quantity:

                updated_units.append(
                    CartItemUnit(
                        key=existing_unit.key,
                        quantity=(
                            existing_unit.quantity
                            - quantity
                        ),
                        base_price=existing_unit.base_price,
                        variation=existing_unit.variation,
                    )
                )

            elif existing_unit.quantity == quantity:
                # Remove this variation completely.

                pass

            else:
                # Do not remove more than exists.
                updated_units.append(existing_unit)

        if unit_found:
            item_found = True

        if updated_units:
            updated_items.append(
                CartItem(
                    item_id=existing_item.item_id,
                    title=existing_item.title,
                    units=updated_units,
                )
            )
        elif not unit_found:
            updated_items.append(existing_item)

    if not item_found:
        raise ValueError(
            f"Item {title} not found in cart."
        )

    return Cart(items=updated_items)


@router.get("/state")
def get_current_state(session_id: str):
    """
    Return the current LangGraph state for a conversation session.
    """
    try:
        if not session_id or not session_id.strip():
            raise ValueError("session_id is missing.")

        state = chatbot_agent.get_state(
            _session_config(session_id)
        )

        return state

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )


@router.post("/cart/add")
def manual_add_to_cart(request: ManualCartRequest):
    try:

        if not request.session_id.strip():
            raise ValueError("session_id is missing.")

        if not request.restaurant_name.strip():
            raise ValueError("restaurant_name is required.")

        if not request.subdomain.strip():
            raise ValueError("subdomain is required.")

        if not request.item_id:
            raise ValueError("item_id is required.")

        if not request.title:
            raise ValueError("title is required.")

        if not _valid_quantity(request.quantity):
            raise ValueError(
                "Quantity must be greater than zero."
            )

        items, error = _fetch_menu_items(
            {
                "subdomain": request.subdomain,
            }
        )

        if error:
            raise ValueError(error)

        menu_item = _find_menu_item(
            items,
            request.item_id,
            request.title,
        )

        if menu_item is None:
            raise ValueError(
                "That item is not available on the current menu."
            )

        current_cart = _get_existing_cart(
            request.session_id
        )

        updated_cart = _add_to_cart(
            current_cart,
            menu_item,
            request.quantity,
            request.variation_id,
        )

        chatbot_agent.update_state(
            _session_config(request.session_id),
            {
                "cart": updated_cart,
                "restaurant_name": request.restaurant_name.strip(),
                "subdomain": request.subdomain.strip(),
                "order_confirmation_pending": False,
            },
        )

        return {
            "success": True,
            "cart": updated_cart,
        }

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )


@router.post("/cart/remove")
def manual_remove_from_cart(request: ManualCartRequest):
    try:

        if not request.session_id.strip():
            raise ValueError("session_id is missing.")

        if not request.item_id:
            raise ValueError("item_id is required.")

        if not request.title:
            raise ValueError("title is required.")

        if not _valid_quantity(request.quantity):
            raise ValueError(
                "Quantity must be greater than zero."
            )

        current_cart = _get_existing_cart(
            request.session_id
        )

        updated_cart = _remove_from_cart(
            current_cart,
            request.item_id,
            request.title,
            request.quantity,
            request.variation_id,
        )

        chatbot_agent.update_state(
            _session_config(request.session_id),
            {
                "cart": updated_cart,
                "order_confirmation_pending": False,
            },
        )

        return {
            "success": True,
            "cart": updated_cart,
        }

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )


@router.post("/cart/clear")
def manual_clear_cart(request: ManualCartRequest):
    try:

        if not request.session_id.strip():
            raise ValueError("session_id is missing.")

        chatbot_agent.update_state(
            _session_config(request.session_id),
            {
                "cart": Cart(items=[]),
                "order_confirmation_pending": False,
            },
        )

        return {
            "success": True,
            "cart": Cart(items=[]),
        }

    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )


@router.post("/orders")
async def chat_order(request: ChatRequest):
    """
    Process a user message through the food-ordering agent
    and stream AI responses using Server-Sent Events (SSE).
    """

    try:

        if not request.session_id or not request.session_id.strip():
            raise ValueError("session_id is missing.")

        if (
            not request.user_message
            or not request.user_message.strip()
        ):
            raise ValueError(
                "user_message cannot be empty."
            )

        if (
            not request.restaurant_name
            or not request.restaurant_name.strip()
        ):
            raise ValueError(
                "restaurant_name is required."
            )

        if (
            not request.subdomain
            or not request.subdomain.strip()
        ):
            raise ValueError(
                "subdomain is required."
            )

        session_id = request.session_id.strip()
        user_message = request.user_message.strip()
        restaurant_name = request.restaurant_name.strip()
        subdomain = request.subdomain.strip()

        graph_config = _session_config(session_id)

        def generate_sse():

            try:

                events = chatbot_agent.stream(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": user_message,
                            }
                        ],
                        "restaurant_name": restaurant_name,
                        "subdomain": subdomain,
                    },
                    graph_config,
                    stream_mode="values",
                )

                for event in events:

                    if not event:
                        continue

                    messages = event.get(
                        "messages",
                        [],
                    )

                    if not messages:
                        continue

                    last_message = messages[-1]
                    message_type = type(last_message).__name__

                    if message_type == "ToolMessage":

                        if getattr(
                            last_message,
                            "status",
                            None,
                        ) == "error":

                            print(
                                f"Tool error: "
                                f"{last_message.content}"
                            )

                        else:

                            content = str(
                                getattr(
                                    last_message,
                                    "content",
                                    "",
                                )
                            )

                            print(
                                f"ToolMessage: "
                                f"{content[:100]}..."
                            )

                    else:

                        content = str(
                            getattr(
                                last_message,
                                "content",
                                "",
                            )
                        )

                        print(
                            f"{message_type}: {content}"
                        )

                    if getattr(
                        last_message,
                        "type",
                        None,
                    ) == "ai":

                        tool_calls = getattr(
                            last_message,
                            "tool_calls",
                            [],
                        )

                        if tool_calls:
                            print(
                                f"Tools called: "
                                f"{tool_calls}"
                            )

                    if message_type == "AIMessage":

                        content = getattr(
                            last_message,
                            "content",
                            "",
                        )

                        tool_calls = getattr(
                            last_message,
                            "tool_calls",
                            [],
                        )

                        if content is None:
                            content = ""

                        if not isinstance(
                            content,
                            str,
                        ):
                            content = str(content)

                        response_data = {
                            "type": "AIMessage",
                            "content": content,
                            "tool_calls": tool_calls,
                        }

                        if content.strip():

                            yield (
                                "data: "
                                + json.dumps(
                                    response_data,
                                    default=str,
                                )
                                + "\n\n"
                            )

                yield "data: [DONE]\n\n"

            except Exception as e:

                error_data = {
                    "type": "error",
                    "content": str(e),
                }

                yield (
                    "data: "
                    + json.dumps(error_data)
                    + "\n\n"
                )

                yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate_sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            },
        )

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=str(e),
        )