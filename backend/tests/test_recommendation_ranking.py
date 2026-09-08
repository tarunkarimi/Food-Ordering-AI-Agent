"""Tests for advanced recommendation ranking."""

from src.services.recommendation_ranking import rank_recommendations


def test_rank_applies_budget_and_preferences():
    menu = [
        {
            "id": "1",
            "title": "Spicy South Indian Dosa",
            "description": "spicy South Indian dinner",
            "base_price": 250,
        },
        {
            "id": "2",
            "title": "Paneer Curry",
            "description": "mild North Indian dinner",
            "base_price": 280,
        },
        {
            "id": "3",
            "title": "Chicken Biryani",
            "description": "spicy rice dish",
            "base_price": 240,
        },
    ]

    result = rank_recommendations(
        menu,
        cuisine_preference="South Indian",
        spice_level="spicy",
        dietary_preference="Vegetarian",
        meal_preference="dinner",
        history_counts={"spicy south indian dosa": 3},
        max_price=300,
    )

    assert result[0]["title"] == "Spicy South Indian Dosa"
    assert result[0]["current_price"] == 250.0
    assert "Chicken Biryani" not in [
        item["title"]
        for item in result
    ]


def test_budget_excludes_over_limit():
    menu = [
        {
            "id": "1",
            "title": "Cheap Dosa",
            "description": "South Indian",
            "base_price": 150,
        },
        {
            "id": "2",
            "title": "Premium Biryani",
            "description": "South Indian",
            "base_price": 450,
        },
    ]

    result = rank_recommendations(
        menu,
        max_price=300,
    )

    assert [
        item["title"]
        for item in result
    ] == ["Cheap Dosa"]


def test_current_menu_price_is_authoritative():
    menu = [
        {
            "id": "1",
            "title": "Biryani",
            "base_price": 299,
        },
    ]

    result = rank_recommendations(
        menu,
        history_counts={"biryani": 5},
    )

    assert result[0]["current_price"] == 299.0


def test_invalid_current_prices_are_skipped():
    result = rank_recommendations(
        [
            {
                "id": "1",
                "title": "Broken Item",
                "base_price": "bad",
            },
            {
                "id": "2",
                "title": "Valid Item",
                "base_price": 100,
            },
        ]
    )

    assert [
        item["title"]
        for item in result
    ] == ["Valid Item"]
