"""Focused tests for persistent user preferences."""

import pytest

from src.db.database import SessionLocal

from src.services.user_preferences import (
    get_or_create_user_preferences,
    get_user_preferences,
    update_user_preferences,
)

from tests.test_authenticated_cart import signup_and_login


def _new_user_id() -> int:
    user_id, _ = signup_and_login()
    return user_id


def test_get_user_preferences_returns_none_when_missing():
    user_id = _new_user_id()

    with SessionLocal() as db:
        result = get_user_preferences(
            db,
            user_id=user_id,
        )

    assert result is None


def test_get_or_create_user_preferences_creates_empty_record():
    user_id = _new_user_id()

    with SessionLocal() as db:
        preferences = get_or_create_user_preferences(
            db,
            user_id=user_id,
        )
        db.commit()

        assert preferences.user_id == user_id
        assert preferences.cuisine_preference is None
        assert preferences.spice_level is None
        assert preferences.dietary_preference is None
        assert preferences.meal_preference is None
        assert preferences.notes is None


def test_get_or_create_user_preferences_reuses_existing_record():
    user_id = _new_user_id()

    with SessionLocal() as db:
        first = get_or_create_user_preferences(
            db,
            user_id=user_id,
        )
        db.commit()
        first_id = first.id

    with SessionLocal() as db:
        second = get_or_create_user_preferences(
            db,
            user_id=user_id,
        )

        assert second.id == first_id


def test_update_user_preferences_creates_and_normalizes_values():
    user_id = _new_user_id()

    with SessionLocal() as db:
        preferences = update_user_preferences(
            db,
            user_id=user_id,
            cuisine_preference="  South Indian  ",
            spice_level="  medium ",
            dietary_preference=" Vegetarian ",
            meal_preference=" Dinner ",
            notes="  Prefer less oil. ",
        )

    assert preferences.user_id == user_id
    assert preferences.cuisine_preference == "South Indian"
    assert preferences.spice_level == "medium"
    assert preferences.dietary_preference == "Vegetarian"
    assert preferences.meal_preference == "Dinner"
    assert preferences.notes == "Prefer less oil."


def test_update_user_preferences_is_partial():
    user_id = _new_user_id()

    with SessionLocal() as db:
        first = update_user_preferences(
            db,
            user_id=user_id,
            cuisine_preference="South Indian",
            spice_level="medium",
        )
        first_id = first.id

    with SessionLocal() as db:
        second = update_user_preferences(
            db,
            user_id=user_id,
            spice_level="hot",
        )

        assert second.id == first_id
        assert second.cuisine_preference == "South Indian"
        assert second.spice_level == "hot"


def test_update_user_preferences_rejects_blank_values():
    user_id = _new_user_id()

    with SessionLocal() as db:
        with pytest.raises(
            ValueError,
            match="cuisine_preference cannot be blank",
        ):
            update_user_preferences(
                db,
                user_id=user_id,
                cuisine_preference="   ",
            )


def test_update_user_preferences_rejects_non_string_values():
    user_id = _new_user_id()

    with SessionLocal() as db:
        with pytest.raises(
            ValueError,
            match="spice_level must be a string",
        ):
            update_user_preferences(
                db,
                user_id=user_id,
                spice_level=123,
            )
