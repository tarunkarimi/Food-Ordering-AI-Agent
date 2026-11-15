"""Tests for advanced recommendation AI tool."""

from unittest.mock import patch
import pytest

from src.agents.tools import cart as cart_tools
from src.agents.tools.advanced_recommendation import (
    advanced_recommend_food,
)
from src.agents.tools.recommendations import (
    get_personalized_recommendations,
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
            "restaurant_name": "Test Restaurant",
            "subdomain": "test",
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
            "src.agents.tools.advanced_recommendation.list_user_memories",
            return_value=[
                {"memory_value": "spicy chicken", "polarity": "like"},
            ],
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
    assert rank_mock.call_args.kwargs["ai_memories"] == [
        {"memory_value": "spicy chicken", "polarity": "like"},
    ]


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
            "src.agents.tools.advanced_recommendation.list_user_memories",
            return_value=[],
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


@pytest.mark.parametrize(
    "caller",
    ["standard", "advanced"],
)
@pytest.mark.parametrize(
    ("menu", "reason"),
    [
        ({"items": []}, "invalid restaurant identity"),
        ({"subdomain": "  ", "items": []}, "invalid restaurant identity"),
        ({"subdomain": "tenant-b", "items": []}, "different restaurant"),
        ({"subdomain": "tenant-a", "items": "malformed"}, "invalid response"),
    ],
    ids=["missing", "blank", "mismatch", "malformed"],
)
def test_recommendation_tools_stop_when_menu_tenant_is_unverified(
    monkeypatch, caller, menu, reason,
):
    requested_urls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return menu

    monkeypatch.setattr(
        cart_tools,
        "request_read_with_retry",
        lambda request: request(),
    )
    monkeypatch.setattr(
        cart_tools.requests,
        "get",
        lambda url, timeout: requested_urls.append(url) or Response(),
    )
    monkeypatch.setattr(
        "src.agents.tools.recommendations.SessionLocal",
        lambda: pytest.fail("standard ranking must not run"),
    )
    monkeypatch.setattr(
        "src.agents.tools.recommendations.get_personalized_recommendations",
        lambda *args, **kwargs: pytest.fail("standard ranking must not run"),
    )
    monkeypatch.setattr(
        "src.agents.tools.advanced_recommendation.SessionLocal",
        lambda: pytest.fail("advanced ranking must not run"),
    )
    monkeypatch.setattr(
        "src.agents.tools.advanced_recommendation.rank_recommendations",
        lambda *args, **kwargs: pytest.fail("advanced ranking must not run"),
    )
    state = {
        "user_id": 41,
        "restaurant_name": "Shared Kitchen",
        "subdomain": "tenant-a",
        "messages": [],
        "cart": {"items": []},
    }

    tool = (
        get_personalized_recommendations
        if caller == "standard"
        else advanced_recommend_food
    )
    result = tool.invoke({"state": state})

    assert "?subdomain=tenant-a" in requested_urls[0]
    assert reason in result["message"].lower()
    assert "recommendations" not in result
    assert state["cart"] == {"items": []}
