"""Tests for context-aware recommendation services."""

import json
from types import SimpleNamespace

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
        items_json=json.dumps(items),
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
        lambda db, user_id, limit, offset: [
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
        lambda db, user_id, limit, offset: [
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
