"""Authenticated reorder API."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.dependencies import AuthenticatedSession, get_current_session
from src.api.routes.cart import _serialize_cart
from src.db.database import get_db
from src.services.reorder import (
    add_reorder_items_to_cart,
    get_reorder_items,
    validate_reorder_items,
)


router = APIRouter()


@router.post("/{order_id}/reorder")
def reorder_order(
    order_id: str,
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    """Validate a historical order and add it to the persistent cart."""

    try:
        reorder = get_reorder_items(
            db,
            user_id=auth.user.id,
            order_id=order_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    try:
        validated_items = validate_reorder_items(
            subdomain=reorder["subdomain"],
            items=reorder["items"],
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    except ConnectionError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    try:
        cart = add_reorder_items_to_cart(
            db,
            user_id=auth.user.id,
            restaurant_name=reorder["restaurant_name"],
            subdomain=reorder["subdomain"],
            items=validated_items,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return {
        "success": True,
        "order_id": reorder["order_id"],
        "restaurant_name": reorder["restaurant_name"],
        "subdomain": reorder["subdomain"],
        "status": reorder["status"],
        "items": validated_items,
        "cart": _serialize_cart(cart),
    }
