from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_current_session
from src.db.database import SessionLocal
from src.services.persistent_ordering_intelligence import (
    build_persistent_ai_ordering_context,
    get_persistent_ordering_profile,
)

router = APIRouter()


@router.get("")
def persistent_ordering_intelligence(
    restaurant_name: str | None = Query(default=None),
    subdomain: str | None = Query(default=None),
    session=Depends(get_current_session),
):
    with SessionLocal() as db:
        return get_persistent_ordering_profile(
            db,
            user_id=session.user.id,
            restaurant_name=restaurant_name,
            subdomain=subdomain,
        )


@router.get("/ai-context")
def persistent_ai_ordering_context(
    restaurant_name: str | None = Query(default=None),
    subdomain: str | None = Query(default=None),
    session=Depends(get_current_session),
):
    with SessionLocal() as db:
        return build_persistent_ai_ordering_context(
            db,
            user_id=session.user.id,
            restaurant_name=restaurant_name,
            subdomain=subdomain,
        )
