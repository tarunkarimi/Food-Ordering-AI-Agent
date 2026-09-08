"""Tests for advanced recommendation AI tool."""

from unittest.mock import patch

from src.agents.tools.advanced_recommendation import (
    advanced_recommend_food,
)


def test_advanced_recommendation_requires_authentication():
    state = {
        "user_id": None,
        "messages": [],
    }

    result = advanced_recommend_food.invoke(
        {"state": state},
    )

    assert "sign in" in result["message"].lower()


def test_advanced_recommendation_uses_budget_and_current_menu():
    state = {
        "user_id": 123,
        "subdomain": "test",
        "restaurant_name": "Test Restaurant",
        "messages": [
            type(
                "Message",
                (),
                {
                    "content": (
                        "I'm vegetarian and want dinner under ?300."
                    )
                },
            )()
        ],
    }

    preferences = type(
        "Preferences",
        (),
        {
            "cuisine_preference": "South Indian",
            "spice_level": "spicy",
            "dietary_preference": "Vegetarian",
            "meal_preference": "dinner",
        },
    )()

    order = type(
        "Order",
        (),
        {
            "items_json": '[{"title":"Dosa","quantity":2}]',
        },
    )()

    with (
        patch(
            "src.agents.tools.advanced_recommendation._fetch_menu_items",
            return_value=(
                [
                    {
                        "id": "1",
                        "title": "Spicy Dosa",
                        "description": "spicy South Indian dinner",
                        "base_price": 200,
                    }
                ],
                None,
            ),
        ),
        patch(
            "src.agents.tools.advanced_recommendation.SessionLocal",
        ) as session_local,
        patch(
            "src.agents.tools.advanced_recommendation.get_user_preferences",
            return_value=preferences,
        ),
        patch(
            "src.agents.tools.advanced_recommendation.list_order_history",
            return_value=[order],
        ),
        patch(
            "src.agents.tools.advanced_recommendation.rank_recommendations",
            return_value=[
                {
                    "item_id": "1",
                    "title": "Spicy Dosa",
                    "current_price": 200.0,
                    "score": 18,
                    "reasons": ["matches your cuisine preference"],
                }
            ],
        ) as rank_mock,
    ):
        result = advanced_recommend_food.invoke(
            {"state": state},
        )

    assert result["recommendations"][0]["title"] == "Spicy Dosa"

    assert rank_mock.call_args.kwargs["max_price"] == 300.0


def test_advanced_recommendation_does_not_mutate_cart():
    state = {
        "user_id": 123,
        "subdomain": "test",
        "restaurant_name": "Test Restaurant",
        "messages": [],
        "cart": {"items": []},
    }

    preferences = type(
        "Preferences",
        (),
        {
            "cuisine_preference": None,
            "spice_level": None,
            "dietary_preference": None,
            "meal_preference": None,
        },
    )()

    with (
        patch(
            "src.agents.tools.advanced_recommendation._fetch_menu_items",
            return_value=(
                [
                    {
                        "id": "1",
                        "title": "Dosa",
                        "base_price": 150,
                    }
                ],
                None,
            ),
        ),
        patch(
            "src.agents.tools.advanced_recommendation.SessionLocal",
        ),
        patch(
            "src.agents.tools.advanced_recommendation.get_user_preferences",
            return_value=preferences,
        ),
        patch(
            "src.agents.tools.advanced_recommendation.list_order_history",
            return_value=[],
        ),
        patch(
            "src.agents.tools.advanced_recommendation.rank_recommendations",
            return_value=[
                {
                    "item_id": "1",
                    "title": "Dosa",
                    "current_price": 150.0,
                    "score": 0,
                    "reasons": [],
                }
            ],
        ),
    ):
        result = advanced_recommend_food.invoke(
            {"state": state},
        )

    assert result["recommendations"]
    assert state["cart"] == {"items": []}
