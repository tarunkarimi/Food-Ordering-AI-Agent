"""Authenticated order-history API."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.dependencies import AuthenticatedSession, get_current_session
from src.db.database import get_db
from src.services.order_history import (
    get_order_history,
    list_order_history,
)
from src.services.order_history_serializer import serialize_order_history


router = APIRouter()


@router.get("")
def get_order_history_list(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return the authenticated user's persistent order history."""

    orders = list_order_history(
        db,
        user_id=auth.user.id,
        limit=limit,
        offset=offset,
    )

    return {
        "orders": [
            serialize_order_history(order)
            for order in orders
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/{order_id}")
def get_authenticated_order_history(
    order_id: str,
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return one persistent order-history record owned by the user."""

    requested_order_id = order_id.strip()

    if not requested_order_id:
        raise HTTPException(
            status_code=400,
            detail="Order ID is required.",
        )

    order = get_order_history(
        db,
        user_id=auth.user.id,
        order_id=requested_order_id,
    )

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order was not found.",
        )

    return serialize_order_history(order)
