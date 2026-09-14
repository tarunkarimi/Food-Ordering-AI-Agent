import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.agents.state import Cart
from src.agents.tools.cart import _fetch_menu_items
from src.api.dependencies import AuthenticatedSession, get_current_session
from src.services.chat_agent import chat_agent_service
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


# ------------------------------------------------------------------
# State endpoint
# ------------------------------------------------------------------

@router.get("/state")
def get_current_state(
    session_id: str,
    auth: AuthenticatedSession = Depends(get_current_session),
):
    """
    Return the current LangGraph state for a conversation session.
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


# ------------------------------------------------------------------
# Manual cart add
# ------------------------------------------------------------------

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
            request.session_id,
            user_id=auth.user.id,
        )

        updated_cart = _add_to_cart(
            current_cart,
            menu_item,
            request.quantity,
            request.variation_id,
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


# ------------------------------------------------------------------
# Manual cart remove
# ------------------------------------------------------------------

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

        current_cart = _get_existing_cart(
            request.session_id,
            user_id=auth.user.id,
        )

        updated_cart = _remove_from_cart(
            current_cart,
            request.item_id,
            request.title,
            request.quantity,
            request.variation_id,
        )

        chat_agent_service.update_state(
            _session_config(
                request.session_id,
                user_id=auth.user.id,
            ),
            {
                "cart": updated_cart,
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


# ------------------------------------------------------------------
# Manual cart clear
# ------------------------------------------------------------------

@router.post("/cart/clear")
def manual_clear_cart(
    request: ClearCartRequest,
    auth: AuthenticatedSession = Depends(get_current_session),
):
    try:
        if not request.session_id.strip():
            raise ValueError("session_id is missing.")

        chat_agent_service.update_state(
            _session_config(
                request.session_id,
                user_id=auth.user.id,
            ),
            {
                "cart": Cart(items=[]),
                "user_id": auth.user.id,
                "order_confirmation_pending": False,
                "finished": False,
            },
        )

        return {
            "success": True,
            "cart": Cart(items=[]),
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


# ------------------------------------------------------------------
# AI chat / order endpoint
# ------------------------------------------------------------------

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

    def generate_sse():
        yield from chat_agent_service.stream_response(
            user_message=user_message,
            restaurant_name=restaurant_name,
            subdomain=subdomain,
            user_id=auth.user.id,
            graph_config=graph_config,
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
