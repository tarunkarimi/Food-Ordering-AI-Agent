"""Focused API tests for authenticated user preferences."""

from fastapi.testclient import TestClient

from src.main import app

from tests.test_authenticated_cart import (
    auth_headers,
    signup_and_login,
)


client = TestClient(app)


def test_preferences_require_authentication():
    response = client.get("/api/preferences")

    assert response.status_code == 401


def test_preferences_return_null_for_new_user():
    _, token = signup_and_login()

    response = client.get(
        "/api/preferences",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json() == {
        "preferences": None,
    }


def test_preferences_patch_creates_preferences():
    _, token = signup_and_login()

    response = client.patch(
        "/api/preferences",
        headers=auth_headers(token),
        json={
            "cuisine_preference": "  South Indian  ",
            "spice_level": " medium ",
            "dietary_preference": " Vegetarian ",
            "meal_preference": " Dinner ",
            "notes": "  Prefer less oil. ",
        },
    )

    assert response.status_code == 200

    data = response.json()["preferences"]

    assert data["user_id"] > 0
    assert data["cuisine_preference"] == "South Indian"
    assert data["spice_level"] == "medium"
    assert data["dietary_preference"] == "Vegetarian"
    assert data["meal_preference"] == "Dinner"
    assert data["notes"] == "Prefer less oil."


def test_preferences_patch_is_partial():
    _, token = signup_and_login()

    first = client.patch(
        "/api/preferences",
        headers=auth_headers(token),
        json={
            "cuisine_preference": "South Indian",
            "spice_level": "medium",
        },
    )

    assert first.status_code == 200

    second = client.patch(
        "/api/preferences",
        headers=auth_headers(token),
        json={
            "spice_level": "hot",
        },
    )

    assert second.status_code == 200

    data = second.json()["preferences"]

    assert data["cuisine_preference"] == "South Indian"
    assert data["spice_level"] == "hot"


def test_preferences_get_returns_saved_values():
    _, token = signup_and_login()

    client.patch(
        "/api/preferences",
        headers=auth_headers(token),
        json={
            "cuisine_preference": "Indian",
            "dietary_preference": "Vegetarian",
        },
    )

    response = client.get(
        "/api/preferences",
        headers=auth_headers(token),
    )

    assert response.status_code == 200

    data = response.json()["preferences"]

    assert data["cuisine_preference"] == "Indian"
    assert data["dietary_preference"] == "Vegetarian"


def test_preferences_are_owned_by_authenticated_user():
    _, token_a = signup_and_login()
    _, token_b = signup_and_login()

    update = client.patch(
        "/api/preferences",
        headers=auth_headers(token_a),
        json={
            "cuisine_preference": "Andhra",
        },
    )

    assert update.status_code == 200

    response = client.get(
        "/api/preferences",
        headers=auth_headers(token_b),
    )

    assert response.status_code == 200

    data = response.json()["preferences"]

    assert data is None


def test_preferences_reject_blank_values():
    _, token = signup_and_login()

    response = client.patch(
        "/api/preferences",
        headers=auth_headers(token),
        json={
            "cuisine_preference": "   ",
        },
    )

    assert response.status_code == 422


def test_preferences_reject_non_string_values():
    _, token = signup_and_login()

    response = client.patch(
        "/api/preferences",
        headers=auth_headers(token),
        json={
            "spice_level": 123,
        },
    )

    assert response.status_code == 422
