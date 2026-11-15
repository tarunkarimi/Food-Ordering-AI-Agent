"""Tests for context-aware recommendation services."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.services.recommendations import get_personalized_recommendations


def _prefs(**kwargs):
    defaults = {
        "cuisine_preference": None,
        "spice_level": None,
        "dietary_preference": None,
        "meal_preference": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _order(items):
    return SimpleNamespace(
        restaurant_name="Sample Kitchen",
        subdomain="sample",
        items_json=json.dumps(items),
    )


@pytest.fixture(autouse=True)
def empty_ai_memory(monkeypatch):
    from src.services import recommendations

    monkeypatch.setattr(
        recommendations,
        "list_user_memories",
        lambda db, user_id: [],
    )


def test_preferences_and_history_rank_current_menu(
    monkeypatch,
):
    from src.services import recommendations

    monkeypatch.setattr(
        recommendations,
        "get_user_preferences",
        lambda db, user_id: _prefs(
            cuisine_preference="South Indian",
            spice_level="spicy",
            dietary_preference=None,
            meal_preference=None,
        ),
    )
    monkeypatch.setattr(
        recommendations,
        "list_order_history",
        lambda db, user_id, limit, offset, **kwargs: [
            _order([{"title": "Spicy Dosa", "quantity": 2}]),
            _order([{"title": "Spicy Dosa", "quantity": 1}]),
        ],
    )

    menu = [
        {
            "id": "1",
            "title": "Spicy Dosa",
            "base_price": 180,
            "description": "Spicy South Indian dosa",
        },
        {
            "id": "2",
            "title": "Paneer Roll",
            "base_price": 200,
            "description": "Mild North Indian roll",
        },
    ]

    result = get_personalized_recommendations(
        object(),
        user_id=1,
        menu_items=menu,
        subdomain="sample",
    )

    assert result["recommendations"][0]["title"] == "Spicy Dosa"
    assert result["recommendations"][0]["current_price"] == 180.0
    assert result["orders_analyzed"] == 2


def test_vegetarian_preference_filters_obvious_non_vegetarian_items(
    monkeypatch,
):
    from src.services import recommendations

    monkeypatch.setattr(
        recommendations,
        "get_user_preferences",
        lambda db, user_id: _prefs(
            dietary_preference="Vegetarian",
        ),
    )
    monkeypatch.setattr(
        recommendations,
        "list_order_history",
        lambda db, user_id, limit, offset: [],
    )

    menu = [
        {
            "id": "1",
            "title": "Chicken Biryani",
            "base_price": 300,
        },
        {
            "id": "2",
            "title": "Vegetable Biryani",
            "base_price": 220,
            "description": "Vegetarian rice dish",
            "dietary": ["vegetarian"],
        },
    ]

    result = get_personalized_recommendations(
        object(),
        user_id=1,
        menu_items=menu,
    )

    titles = [
        item["title"]
        for item in result["recommendations"]
    ]

    assert "Chicken Biryani" not in titles
    assert "Vegetable Biryani" in titles


def test_historical_prices_are_not_returned(
    monkeypatch,
):
    from src.services import recommendations

    monkeypatch.setattr(
        recommendations,
        "get_user_preferences",
        lambda db, user_id: _prefs(),
    )
    monkeypatch.setattr(
        recommendations,
        "list_order_history",
        lambda db, user_id, limit, offset, **kwargs: [
            _order(
                [
                    {
                        "title": "Biryani",
                        "quantity": 1,
                        "unit_price": 99,
                    }
                ]
            )
        ],
    )

    result = get_personalized_recommendations(
        object(),
        user_id=1,
        menu_items=[
            {
                "id": "1",
                "title": "Biryani",
                "base_price": 249,
            }
        ],
    )

    recommendation = result["recommendations"][0]

    assert recommendation["current_price"] == 249.0
    assert "unit_price" not in recommendation


def test_invalid_menu_prices_are_excluded(
    monkeypatch,
):
    from src.services import recommendations

    monkeypatch.setattr(
        recommendations,
        "get_user_preferences",
        lambda db, user_id: _prefs(),
    )
    monkeypatch.setattr(
        recommendations,
        "list_order_history",
        lambda db, user_id, limit, offset: [],
    )

    result = get_personalized_recommendations(
        object(),
        user_id=1,
        menu_items=[
            {
                "id": "1",
                "title": "Bad Item",
                "base_price": "invalid",
            },
            {
                "id": "2",
                "title": "Good Item",
                "base_price": 100,
            },
        ],
    )

    assert [
        item["title"]
        for item in result["recommendations"]
    ] == ["Good Item"]


def test_conversational_memories_rank_likes_and_exclude_dislikes(
    monkeypatch,
):
    from src.services import recommendations

    monkeypatch.setattr(
        recommendations,
        "get_user_preferences",
        lambda db, user_id: None,
    )
    monkeypatch.setattr(
        recommendations,
        "list_order_history",
        lambda db, user_id, limit, offset: [],
    )
    monkeypatch.setattr(
        recommendations,
        "list_user_memories",
        lambda db, user_id: [
            {"memory_value": "spicy chicken", "polarity": "like"},
            {"memory_value": "paneer", "polarity": "dislike"},
        ],
    )

    result = get_personalized_recommendations(
        object(),
        user_id=42,
        menu_items=[
            {
                "id": "chicken",
                "title": "Spicy Chicken Tikka",
                "description": "chargrilled chicken",
                "ingredients": ["chicken", "chili", "yogurt"],
                "ingredients_complete": True,
                "dietary": ["non-vegetarian"],
                "base_price": 240,
            },
            {
                "id": "paneer",
                "title": "Paneer Tikka",
                "description": "vegetarian starter",
                "base_price": 200,
            },
            {
                "id": "rice",
                "title": "Vegetable Rice",
                "description": "mild rice",
                "ingredients": ["rice", "vegetables"],
                "ingredients_complete": True,
                "dietary": ["vegetarian"],
                "base_price": 130,
            },
        ],
    )

    assert result["recommendations"][0]["title"] == "Spicy Chicken Tikka"
    assert all(
        item["title"] != "Paneer Tikka"
        for item in result["recommendations"]
    )
    assert result["preferences_used"] is True


def test_personalized_service_enforces_vegan_menu_evidence(monkeypatch):
    from src.services import recommendations

    monkeypatch.setattr(
        recommendations,
        "get_user_preferences",
        lambda db, user_id: _prefs(dietary_preference="Vegan"),
    )
    monkeypatch.setattr(
        recommendations,
        "list_order_history",
        lambda db, user_id, limit, offset: [],
    )

    result = get_personalized_recommendations(
        object(),
        user_id=42,
        menu_items=[
            {
                "id": "verified",
                "title": "Chickpea Bowl",
                "ingredients": ["chickpeas", "lettuce"],
                "ingredients_complete": True,
                "base_price": 120,
            },
            {
                "id": "unknown",
                "title": "House Bowl",
                "base_price": 110,
            },
            {
                "id": "animal",
                "title": "Chicken Bowl",
                "dietary": ["vegan"],
                "base_price": 130,
            },
        ],
    )

    assert [item["title"] for item in result["recommendations"]] == [
        "Chickpea Bowl"
    ]


def test_history_frequency_and_recency_influence_ranking(monkeypatch):
    from src.services import recommendations

    monkeypatch.setattr(
        recommendations,
        "get_user_preferences",
        lambda db, user_id: _prefs(cuisine_preference="Indian"),
    )
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        recommendations,
        "list_order_history",
        lambda db, user_id, limit, offset, **kwargs: [
            SimpleNamespace(
                status="confirmed",
                restaurant_name="Sample Kitchen",
                subdomain="sample",
                created_at=now - timedelta(days=1),
                items_json=json.dumps([
                    {"title": "Recent Indian Curry", "quantity": 2},
                    {"title": "Recent Indian Curry", "quantity": 1},
                ]),
            ),
            SimpleNamespace(
                status="confirmed",
                restaurant_name="Sample Kitchen",
                subdomain="sample",
                created_at=now - timedelta(days=2),
                items_json=json.dumps([
                    {"title": "Recent Indian Curry", "quantity": 1},
                ]),
            ),
            SimpleNamespace(
                status="cancelled",
                restaurant_name="Sample Kitchen",
                subdomain="sample",
                created_at=now,
                items_json=json.dumps([
                    {"title": "Cancelled Favorite", "quantity": 5},
                ]),
            ),
            SimpleNamespace(
                status="confirmed",
                restaurant_name="Sample Kitchen",
                subdomain="sample",
                created_at=now - timedelta(days=120),
                items_json=json.dumps([
                    {"title": "Old Indian Curry", "quantity": 1},
                    {"title": "Old Indian Curry", "quantity": 1},
                ]),
            ),
        ],
    )

    result = get_personalized_recommendations(
        object(),
        user_id=42,
        menu_items=[
            {"id": "recent", "title": "Recent Indian Curry", "base_price": 200},
            {"id": "old", "title": "Old Indian Curry", "base_price": 200},
            {"id": "cancelled", "title": "Cancelled Favorite", "base_price": 100},
        ],
        subdomain="sample",
    )

    assert result["recommendations"][0]["title"] == "Recent Indian Curry"
    assert "frequently ordered favorite" in result["recommendations"][0]["reasons"]
    assert "ordered recently" in result["recommendations"][0]["reasons"]
    cancelled_candidate = next(
        item
        for item in result["recommendations"]
        if item["title"] == "Cancelled Favorite"
    )
    assert not any("ordered" in reason for reason in cancelled_candidate["reasons"])


def test_service_scopes_preferences_memories_and_history_to_authenticated_user(
    monkeypatch,
):
    from src.services import recommendations

    observed = []
    monkeypatch.setattr(
        recommendations,
        "get_user_preferences",
        lambda db, user_id: observed.append(("preferences", user_id)) or None,
    )
    monkeypatch.setattr(
        recommendations,
        "list_user_memories",
        lambda db, user_id: observed.append(("memories", user_id)) or [],
    )
    monkeypatch.setattr(
        recommendations,
        "list_order_history",
        lambda db, user_id, limit, offset: observed.append(("history", user_id)) or [],
    )

    get_personalized_recommendations(
        object(), user_id=808, menu_items=[]
    )

    assert observed == [
        ("preferences", 808),
        ("memories", 808),
        ("history", 808),
    ]


def test_unknown_dislike_metadata_returns_empty_limited_result(monkeypatch):
    from src.services import recommendations

    monkeypatch.setattr(recommendations, "get_user_preferences", lambda db, user_id: None)
    monkeypatch.setattr(recommendations, "list_order_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        recommendations,
        "list_user_memories",
        lambda db, user_id: [
            {"memory_value": "paneer", "polarity": "dislike"},
        ],
    )
    result = get_personalized_recommendations(
        object(), user_id=42,
        menu_items=[{"id": "meal", "title": "House Special", "base_price": 100}],
    )
    assert result["recommendations"] == []
    assert result["recommendations_limited"] is True
    assert "could not be verified" in result["safety_notice"]


def test_verified_nonmatch_and_multiple_dislikes_are_handled(monkeypatch):
    from src.services import recommendations

    monkeypatch.setattr(recommendations, "get_user_preferences", lambda db, user_id: None)
    monkeypatch.setattr(recommendations, "list_order_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        recommendations,
        "list_user_memories",
        lambda db, user_id: [
            {"memory_value": "paneer", "polarity": "dislike"},
            {"memory_value": "peanut", "polarity": "dislike"},
        ],
    )
    result = get_personalized_recommendations(
        object(), user_id=42,
        menu_items=[
            {
                "id": "safe", "title": "Vegetable Bowl", "base_price": 100,
                "ingredients": ["rice", "vegetables"], "ingredients_complete": True,
            },
            {
                "id": "known", "title": "Paneer Bowl", "base_price": 110,
                "ingredients": ["paneer", "rice"], "ingredients_complete": True,
            },
        ],
    )
    assert [item["title"] for item in result["recommendations"]] == ["Vegetable Bowl"]


def test_positive_memory_cannot_override_negative_restriction(monkeypatch):
    from src.services import recommendations

    monkeypatch.setattr(recommendations, "get_user_preferences", lambda db, user_id: None)
    monkeypatch.setattr(recommendations, "list_order_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        recommendations,
        "list_user_memories",
        lambda db, user_id: [
            {"memory_value": "paneer", "polarity": "like"},
            {"memory_value": "paneer", "polarity": "dislike"},
        ],
    )
    result = get_personalized_recommendations(
        object(), user_id=42,
        menu_items=[{
            "id": "paneer", "title": "Paneer Curry", "base_price": 100,
            "ingredients": ["paneer", "tomato"], "ingredients_complete": True,
        }],
    )
    assert result["recommendations"] == []


def test_history_signals_do_not_cross_restaurant_tenants(monkeypatch):
    from src.services import recommendations

    monkeypatch.setattr(recommendations, "get_user_preferences", lambda db, user_id: None)
    monkeypatch.setattr(recommendations, "list_user_memories", lambda db, user_id: [])
    monkeypatch.setattr(
        recommendations,
        "list_order_history",
        lambda *args, **kwargs: [
            SimpleNamespace(
                restaurant_name="Shared Name", subdomain="tenant-a",
                status="confirmed", created_at=datetime.now(timezone.utc),
                items_json=json.dumps([{"title": "Same Dish"}]),
            ),
            SimpleNamespace(
                restaurant_name="Shared Name", subdomain="tenant-b",
                status="confirmed", created_at=datetime.now(timezone.utc),
                items_json=json.dumps([{"title": "Same Dish"}] * 4),
            ),
        ],
    )
    result = get_personalized_recommendations(
        object(), user_id=42,
        menu_items=[{"id": "dish", "title": "Same Dish", "base_price": 100}],
        restaurant_name="Shared Name", subdomain="tenant-a",
    )
    assert result["orders_analyzed"] == 1
    assert "frequently ordered favorite" not in result["recommendations"][0]["reasons"]


def test_service_applies_budget_and_returns_only_compliant_combinations(
    monkeypatch,
):
    from src.services import recommendations

    monkeypatch.setattr(
        recommendations,
        "get_user_preferences",
        lambda db, user_id: _prefs(),
    )
    monkeypatch.setattr(
        recommendations,
        "list_order_history",
        lambda db, user_id, limit, offset: [],
    )
    result = get_personalized_recommendations(
        object(),
        user_id=42,
        menu_items=[
            {"id": "main", "title": "Curry", "base_price": 240},
            {"id": "side", "title": "Rice", "base_price": 100},
            {"id": "drink", "title": "Lassi", "base_price": 80},
            {"id": "too-high", "title": "Thali", "base_price": 500},
        ],
        max_price=350,
    )

    assert all(item["current_price"] <= 350 for item in result["recommendations"])
    assert result["budget_applied"] == 350
    assert result["budget_combinations"]
    assert all(combo["estimated_total"] <= 350 for combo in result["budget_combinations"])
