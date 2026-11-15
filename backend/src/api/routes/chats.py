import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text as sql_text

from src.agents.state import Cart
from src.agents.tools.cart import _fetch_menu_items
from src.api.dependencies import AuthenticatedSession, get_current_session
from src.services.chat_agent import chat_agent_service
from src.db.database import SessionLocal
from src.services.langgraph_cart import (
    load_langgraph_cart,
    persist_langgraph_cart,
)
from src.services.chat_cart import (
    add_to_cart,
    build_authoritative_unit,
    build_session_config,
    find_menu_item,
    remove_from_cart,
)


logger = logging.getLogger(__name__)

router = APIRouter()


# ------------------------------------------------------------------
# Application services
# ------------------------------------------------------------------

chatbot_agent = chat_agent_service.agent


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class ChatRequest(BaseModel):
    user_message: str = Field(
        ...,
        min_length=1,
        description="Message from the customer.",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Conversation session identifier.",
    )
    restaurant_name: str = Field(
        ...,
        min_length=1,
        description="Restaurant name.",
    )
    subdomain: str = Field(
        ...,
        min_length=1,
        description="Restaurant subdomain.",
    )


class ManualCartRequest(BaseModel):
    session_id: str = Field(
        ...,
        min_length=1,
        description="Conversation session identifier.",
    )
    restaurant_name: str = Field(
        ...,
        min_length=1,
        description="Restaurant name.",
    )
    subdomain: str = Field(
        ...,
        min_length=1,
        description="Restaurant subdomain.",
    )
    item_id: Optional[str] = None
    title: Optional[str] = None
    quantity: int = Field(
        default=1,
        gt=0,
        description="Quantity to add.",
    )
    variation_id: Optional[str] = None


class ManualCartItemRequest(BaseModel):
    session_id: str = Field(
        ...,
        min_length=1,
        description="Conversation session identifier.",
    )
    restaurant_name: Optional[str] = None
    subdomain: Optional[str] = None
    item_id: Optional[str] = None
    title: Optional[str] = None
    quantity: int = Field(
        default=1,
        gt=0,
        description="Quantity to remove.",
    )
    variation_id: Optional[str] = None


class ClearCartRequest(BaseModel):
    session_id: str = Field(
        ...,
        min_length=1,
        description="Conversation session identifier.",
    )
    restaurant_name: Optional[str] = None
    subdomain: Optional[str] = None


# ------------------------------------------------------------------
# Service compatibility aliases
# ------------------------------------------------------------------

# Keep the historical private helper names available so existing tests
# and internal callers continue to work while the implementation lives
# in the service layer.
_session_config = build_session_config
_find_menu_item = find_menu_item
_authoritative_unit = build_authoritative_unit
_add_to_cart = add_to_cart
_remove_from_cart = remove_from_cart


def _get_state_values(
    session_id: str,
    user_id: int,
) -> dict:
    state = chat_agent_service.get_state(
        _session_config(
            session_id,
            user_id=user_id,
        )
    )

    values = getattr(state, "values", None)

    if isinstance(values, dict):
        return values

    return {}


def _get_existing_cart(
    session_id: str,
    *,
    user_id: int,
    restaurant_name: Optional[str] = None,
    subdomain: Optional[str] = None,
) -> Cart:
    values = _get_state_values(
        session_id,
        user_id,
    )

    restaurant_name = (
        restaurant_name
        or values.get("restaurant_name")
    )

    subdomain = (
        subdomain
        or values.get("subdomain")
    )

    if restaurant_name and subdomain:
        with SessionLocal() as db:
            return load_langgraph_cart(
                db,
                user_id=user_id,
                restaurant_name=restaurant_name.strip(),
                subdomain=subdomain.strip(),
            )

    cart = values.get("cart")

    if isinstance(cart, Cart):
        return cart

    if isinstance(cart, dict):
        return Cart.model_validate(cart)

    return Cart(items=[])


def _persist_authenticated_cart(
    *,
    user_id: int,
    restaurant_name: str,
    subdomain: str,
    cart: Cart,
) -> None:
    with SessionLocal() as db:
        persist_langgraph_cart(
            db,
            user_id=user_id,
            restaurant_name=restaurant_name.strip(),
            subdomain=subdomain.strip(),
            cart=cart,
        )


def _infer_variation_id(
    cart: Cart,
    item_id: str,
) -> Optional[str]:
    for item in cart.items:
        if item.item_id != item_id:
            continue

        if len(item.units) != 1:
            return None

        unit = item.units[0]

        if unit.variation is not None and unit.variation.id:
            return unit.variation.id

        key_parts = str(unit.key or "").split("|", 1)

        if len(key_parts) == 2 and key_parts[1]:
            if key_parts[1] != "no_variant":
                return key_parts[1]

        return None

    return None


@router.get("/state")
def get_current_state(
    session_id: str,
    restaurant_name: Optional[str] = None,
    subdomain: Optional[str] = None,
    auth: AuthenticatedSession = Depends(get_current_session),
):
    """
    Return authenticated state with the persistent cart restored.
    """
    try:
        if not session_id or not session_id.strip():
            raise ValueError("session_id is missing.")

        state = chat_agent_service.get_state(
            _session_config(
                session_id,
                user_id=auth.user.id,
            )
        )

        values = getattr(state, "values", None)

        if isinstance(values, dict):
            restaurant_name = (
                restaurant_name
                or values.get("restaurant_name")
            )

            subdomain = (
                subdomain
                or values.get("subdomain")
            )

            if restaurant_name and subdomain:
                with SessionLocal() as db:
                    values["cart"] = load_langgraph_cart(
                        db,
                        user_id=auth.user.id,
                        restaurant_name=restaurant_name.strip(),
                        subdomain=subdomain.strip(),
                    )

                values["restaurant_name"] = restaurant_name.strip()
                values["subdomain"] = subdomain.strip()

        return state

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception:
        logger.exception(
            "Failed to retrieve state for authenticated session."
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve the current session state.",
        )


@router.post("/cart/add")
def manual_add_to_cart(
    request: ManualCartRequest,
    auth: AuthenticatedSession = Depends(get_current_session),
):
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

        items, error = _fetch_menu_items(
            {
                "subdomain": request.subdomain.strip(),
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
            request.session_id,
            user_id=auth.user.id,
            restaurant_name=request.restaurant_name,
            subdomain=request.subdomain,
        )

        variation_id = request.variation_id

        # If the frontend did not send a variation ID, recover it
        # from the existing persistent cart when there is exactly
        # one unit for this item.
        if not variation_id:
            variation_id = _infer_variation_id(
                current_cart,
                request.item_id,
            )

        updated_cart = _add_to_cart(
            current_cart,
            menu_item,
            request.quantity,
            variation_id,
        )

        _persist_authenticated_cart(
            user_id=auth.user.id,
            restaurant_name=request.restaurant_name,
            subdomain=request.subdomain,
            cart=updated_cart,
        )

        chat_agent_service.update_state(
            _session_config(
                request.session_id,
                user_id=auth.user.id,
            ),
            {
                "cart": updated_cart,
                "restaurant_name": request.restaurant_name.strip(),
                "subdomain": request.subdomain.strip(),
                "user_id": auth.user.id,
                "order_confirmation_pending": False,
                "finished": False,
            },
        )

        return {
            "success": True,
            "cart": updated_cart,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception:
        logger.exception(
            "Unexpected error while adding item to authenticated cart."
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to add the item to the cart.",
        )


@router.post("/cart/remove")
def manual_remove_from_cart(
    request: ManualCartItemRequest,
    auth: AuthenticatedSession = Depends(get_current_session),
):
    try:
        if not request.session_id.strip():
            raise ValueError("session_id is missing.")

        if not request.item_id:
            raise ValueError("item_id is required.")

        if not request.title:
            raise ValueError("title is required.")

        values = _get_state_values(
            request.session_id,
            auth.user.id,
        )

        restaurant_name = (
            request.restaurant_name
            or values.get("restaurant_name")
        )

        subdomain = (
            request.subdomain
            or values.get("subdomain")
        )

        if not restaurant_name or not subdomain:
            raise ValueError(
                "Restaurant context is required for cart removal."
            )

        current_cart = _get_existing_cart(
            request.session_id,
            user_id=auth.user.id,
            restaurant_name=restaurant_name,
            subdomain=subdomain,
        )

        variation_id = request.variation_id

        if not variation_id:
            variation_id = _infer_variation_id(
                current_cart,
                request.item_id,
            )

        updated_cart = _remove_from_cart(
            current_cart,
            request.item_id,
            request.title,
            request.quantity,
            variation_id,
        )

        _persist_authenticated_cart(
            user_id=auth.user.id,
            restaurant_name=restaurant_name,
            subdomain=subdomain,
            cart=updated_cart,
        )

        chat_agent_service.update_state(
            _session_config(
                request.session_id,
                user_id=auth.user.id,
            ),
            {
                "cart": updated_cart,
                "restaurant_name": restaurant_name.strip(),
                "subdomain": subdomain.strip(),
                "user_id": auth.user.id,
                "order_confirmation_pending": False,
                "finished": False,
            },
        )

        return {
            "success": True,
            "cart": updated_cart,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception:
        logger.exception(
            "Unexpected error while removing item from authenticated cart."
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to remove the item from the cart.",
        )


@router.post("/cart/clear")
def manual_clear_cart(
    request: ClearCartRequest,
    auth: AuthenticatedSession = Depends(get_current_session),
):
    try:
        if not request.session_id.strip():
            raise ValueError("session_id is missing.")

        values = _get_state_values(
            request.session_id,
            auth.user.id,
        )

        restaurant_name = (
            request.restaurant_name
            or values.get("restaurant_name")
        )

        subdomain = (
            request.subdomain
            or values.get("subdomain")
        )

        if not restaurant_name or not subdomain:
            raise ValueError(
                "Restaurant context is required to clear the cart."
            )

        empty_cart = Cart(items=[])

        _persist_authenticated_cart(
            user_id=auth.user.id,
            restaurant_name=restaurant_name,
            subdomain=subdomain,
            cart=empty_cart,
        )

        chat_agent_service.update_state(
            _session_config(
                request.session_id,
                user_id=auth.user.id,
            ),
            {
                "cart": empty_cart,
                "restaurant_name": restaurant_name.strip(),
                "subdomain": subdomain.strip(),
                "user_id": auth.user.id,
                "order_confirmation_pending": False,
                "finished": False,
            },
        )

        return {
            "success": True,
            "cart": empty_cart,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception:
        logger.exception(
            "Unexpected error while clearing authenticated cart."
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to clear the cart.",
        )



@router.post("/orders")
async def chat_order(
    request: ChatRequest,
    auth: AuthenticatedSession = Depends(get_current_session),
):
    """
    Process a user message through the food-ordering agent and stream
    AI responses using Server-Sent Events (SSE).

    The authenticated user's ID is included in graph state and the
    LangGraph thread is namespaced by that user.
    """

    session_id = request.session_id.strip()
    user_message = request.user_message.strip()
    restaurant_name = request.restaurant_name.strip()
    subdomain = request.subdomain.strip()

    graph_config = _session_config(
        session_id,
        user_id=auth.user.id,
    )
    message_timestamp = datetime.now(timezone.utc)

    def generate_sse():
        yield from chat_agent_service.stream_response(
            user_message=user_message,
            restaurant_name=restaurant_name,
            subdomain=subdomain,
            user_id=auth.user.id,
            graph_config=graph_config,
            message_timestamp=message_timestamp,
            agent=chatbot_agent,
        )

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
