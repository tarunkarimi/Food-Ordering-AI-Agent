"""Ordering intelligence API."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.dependencies import get_current_session, get_db
from src.services.ordering_intelligence import (
    build_ai_ordering_context,
    build_ordering_intelligence,
    build_smart_reorder_suggestions,
)

router = APIRouter()


@router.get("")
def get_ordering_intelligence(
    restaurant_name: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    session=Depends(get_current_session),
):
    return build_ordering_intelligence(
        db,
        user_id=session.user_id,
        restaurant_name=restaurant_name,
        limit=limit,
    )


@router.get("/reorder-suggestions")
def get_reorder_suggestions(
    restaurant_name: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
    session=Depends(get_current_session),
):
    return {
        "suggestions": build_smart_reorder_suggestions(
            db,
            user_id=session.user_id,
            restaurant_name=restaurant_name,
            limit=limit,
        )
    }


@router.get("/ai-context")
def get_ai_ordering_context(
    restaurant_name: str | None = Query(default=None),
    db: Session = Depends(get_db),
    session=Depends(get_current_session),
):
    return build_ai_ordering_context(
        db,
        user_id=session.user_id,
        restaurant_name=restaurant_name,
    )
