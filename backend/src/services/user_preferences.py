"""Persistent user preference services."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import UserPreferences


_PREFERENCE_FIELDS = (
    "cuisine_preference",
    "spice_level",
    "dietary_preference",
    "meal_preference",
    "notes",
)


def _normalize_value(
    value: str | None,
    *,
    field_name: str,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"{field_name} cannot be blank.")

    return normalized


def get_user_preferences(
    db: Session,
    *,
    user_id: int,
) -> UserPreferences | None:
    """Return preferences belonging to the authenticated user."""

    return db.scalar(
        select(UserPreferences).where(
            UserPreferences.user_id == user_id,
        )
    )


def get_or_create_user_preferences(
    db: Session,
    *,
    user_id: int,
) -> UserPreferences:
    """Return the user's preferences, creating an empty record if needed."""

    preferences = get_user_preferences(
        db,
        user_id=user_id,
    )

    if preferences is not None:
        return preferences

    preferences = UserPreferences(user_id=user_id)

    db.add(preferences)
    db.flush()

    return preferences


def update_user_preferences(
    db: Session,
    *,
    user_id: int,
    cuisine_preference: str | None = None,
    spice_level: str | None = None,
    dietary_preference: str | None = None,
    meal_preference: str | None = None,
    notes: str | None = None,
) -> UserPreferences:
    """Create or partially update the authenticated user's preferences.

    A value of None means that the field is not being changed. To clear a
    preference, an explicit clear operation should be added at the API layer
    rather than overloading None here.
    """

    preferences = get_or_create_user_preferences(
        db,
        user_id=user_id,
    )

    values = {
        "cuisine_preference": cuisine_preference,
        "spice_level": spice_level,
        "dietary_preference": dietary_preference,
        "meal_preference": meal_preference,
        "notes": notes,
    }

    for field_name in _PREFERENCE_FIELDS:
        value = values[field_name]

        if value is None:
            continue

        setattr(
            preferences,
            field_name,
            _normalize_value(
                value,
                field_name=field_name,
            ),
        )

    db.commit()
    db.refresh(preferences)

    return preferences
