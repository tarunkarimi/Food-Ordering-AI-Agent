"""Authenticated ordering-intelligence API."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.agents.tools.cart import _fetch_menu_items_for_tenant
from src.api.dependencies import AuthenticatedSession, get_current_session
from src.db.database import get_db
from src.services.order_history import (
    list_order_history,
    resolve_unique_order_subdomain,
)
from src.services.ordering_intelligence import (
    build_ai_ordering_context,
    build_ordering_intelligence,
    build_smart_reorder_suggestions,
    filter_reorder_suggestions_to_menu,
)

router = APIRouter()


@router.get("")
def get_ordering_intelligence(
    restaurant_name: str | None = Query(default=None, max_length=255),
    subdomain: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=100),
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return build_ordering_intelligence(
        db,
        user_id=auth.user.id,
        restaurant_name=restaurant_name,
        limit=limit,
        subdomain=subdomain,
    )


@router.get("/reorder-suggestions")
def get_reorder_suggestions(
    restaurant_name: str | None = Query(default=None, max_length=255),
    subdomain: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=5, ge=1, le=10),
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    tenant = subdomain.strip() if isinstance(subdomain, str) else ""
    if not tenant:
        tenant = resolve_unique_order_subdomain(
            db,
            user_id=auth.user.id,
        ) or ""
    if not tenant:
        return {"suggestions": []}

    history_filters = {}
    if restaurant_name and restaurant_name.strip():
        history_filters["restaurant_name"] = restaurant_name.strip()
    history_filters["subdomain"] = tenant
    recent_orders = list_order_history(
        db,
        user_id=auth.user.id,
        limit=50,
        offset=0,
        **history_filters,
    )
    recent_orders = [
        order
        for order in recent_orders
        if getattr(order, "subdomain", None) == tenant
        and (
            not restaurant_name
            or str(getattr(order, "restaurant_name", "")).strip().casefold()
            == restaurant_name.strip().casefold()
        )
        and str(getattr(order, "status", "")).strip().lower()
        not in {"cancelled", "canceled", "failed", "rejected"}
    ]
    if not recent_orders:
        return {"suggestions": []}

    # Suggestions are scoped to the most recently ordered restaurant so each
    # item can be checked against that tenant's current authoritative menu.
    latest_order = recent_orders[0]
    if getattr(latest_order, "subdomain", None) != tenant:
        return {"suggestions": []}
    menu_items, error = _fetch_menu_items_for_tenant(tenant)
    if error:
        raise HTTPException(
            status_code=503,
            detail="Current menu unavailable; reorder suggestions are temporarily unavailable.",
        )
    scoped_restaurant = str(
        restaurant_name or getattr(latest_order, "restaurant_name", "")
    ).strip()
    suggestions = build_smart_reorder_suggestions(
        db,
        user_id=auth.user.id,
        restaurant_name=scoped_restaurant,
        limit=10,
        subdomain=tenant,
    )
    return {
        "suggestions": filter_reorder_suggestions_to_menu(
            suggestions,
            menu_items,
        )[:limit]
    }


@router.get("/ai-context")
def get_ai_ordering_context(
    restaurant_name: str | None = Query(default=None, max_length=255),
    subdomain: str | None = Query(default=None, max_length=255),
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return build_ai_ordering_context(
        db,
        user_id=auth.user.id,
        restaurant_name=restaurant_name,
        subdomain=subdomain,
    )
