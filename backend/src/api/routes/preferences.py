"""Authenticated user-preferences API."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from sqlalchemy.orm import Session

from src.api.dependencies import AuthenticatedSession, get_current_session
from src.db.database import get_db
from src.services.user_preferences import (
    get_user_preferences,
    update_user_preferences,
)


router = APIRouter()


class UserPreferencesUpdate(BaseModel):
    """Fields that can be updated on the authenticated user's preferences."""

    cuisine_preference: str | None = None
    spice_level: str | None = None
    dietary_preference: str | None = None
    meal_preference: str | None = None
    notes: str | None = None


def _serialize_preferences(preferences) -> dict[str, Any] | None:
    if preferences is None:
        return None

    return {
        "id": preferences.id,
        "user_id": preferences.user_id,
        "cuisine_preference": preferences.cuisine_preference,
        "spice_level": preferences.spice_level,
        "dietary_preference": preferences.dietary_preference,
        "meal_preference": preferences.meal_preference,
        "notes": preferences.notes,
        "created_at": preferences.created_at,
        "updated_at": preferences.updated_at,
    }


@router.get("")
def get_preferences(
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return the authenticated user's persistent preferences."""

    preferences = get_user_preferences(
        db,
        user_id=auth.user.id,
    )

    return {
        "preferences": _serialize_preferences(preferences),
    }


@router.patch("")
def patch_preferences(
    payload: UserPreferencesUpdate,
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create or partially update the authenticated user's preferences."""

    try:
        preferences = update_user_preferences(
            db,
            user_id=auth.user.id,
            cuisine_preference=payload.cuisine_preference,
            spice_level=payload.spice_level,
            dietary_preference=payload.dietary_preference,
            meal_preference=payload.meal_preference,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return {
        "preferences": _serialize_preferences(preferences),
    }
