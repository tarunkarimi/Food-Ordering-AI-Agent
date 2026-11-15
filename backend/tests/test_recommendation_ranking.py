"""Tests for advanced recommendation ranking."""

import pytest

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


def test_remembered_positive_food_preference_boosts_matching_menu_item():
    result = rank_recommendations(
        [
            {
                "id": "1",
                "title": "Spicy Chicken Tikka",
                "description": "Chargrilled chicken with chili.",
                "base_price": 250,
            },
            {
                "id": "2",
                "title": "Vegetable Pulao",
                "description": "Mild rice dish.",
                "base_price": 100,
            },
        ],
        ai_memories=[
            {"memory_value": "spicy chicken", "polarity": "like"},
        ],
    )

    assert result[0]["title"] == "Spicy Chicken Tikka"
    assert result[0]["score"] == 6
    assert "matches a food you like" in result[0]["reasons"]


def test_remembered_disliked_food_is_excluded_from_current_menu():
    result = rank_recommendations(
        [
            {
                "id": "1",
                "title": "Paneer Tikka",
                "base_price": 220,
            },
            {
                "id": "2",
                "title": "Chili Chicken",
                "ingredients": ["chicken", "chili"],
                "ingredients_complete": True,
                "base_price": 200,
            },
        ],
        ai_memories=[{"memory_value": "paneer", "polarity": "dislike"}],
    )

    assert [item["title"] for item in result] == ["Chili Chicken"]


def test_memory_exclusions_preserve_dietary_and_budget_constraints():
    result = rank_recommendations(
        [
            {
                "id": "1",
                "title": "Paneer Tikka",
                "description": "vegetarian spicy food",
                "base_price": 200,
            },
            {
                "id": "2",
                "title": "Chicken Tikka",
                "description": "spicy chicken dinner",
                "base_price": 200,
            },
            {
                "id": "3",
                "title": "Vegetable Curry",
                "description": "mild vegetarian meal",
                "base_price": 450,
            },
        ],
        dietary_preference="vegetarian",
        max_price=300,
        ai_memories=[
            {"memory_value": "paneer", "polarity": "dislike"},
            {"memory_value": "spicy", "polarity": "like"},
        ],
    )

    assert [item["title"] for item in result] == []


def test_vegan_preference_requires_verified_vegan_menu_data():
    result = rank_recommendations(
        [
            {
                "id": "vegan-label",
                "title": "Tofu Bowl",
                "description": "Vegetable and tofu bowl",
                "dietary": ["vegan"],
                "base_price": 180,
            },
            {
                "id": "verified-ingredients",
                "title": "Garden Bowl",
                "ingredients": ["lettuce", "chickpeas", "olive oil"],
                "ingredients_complete": True,
                "base_price": 160,
            },
            {
                "id": "animal-ingredient",
                "title": "Vegan Chicken Bowl",
                "description": "Chicken with vegetables",
                "dietary": ["vegan"],
                "base_price": 190,
            },
            {
                "id": "unknown",
                "title": "Chef's Special Bowl",
                "description": "A house special",
                "base_price": 170,
            },
        ],
        dietary_preference="Vegan",
    )

    assert [item["item_id"] for item in result] == [
        "verified-ingredients",
        "vegan-label",
    ]


def test_disliked_ingredient_excludes_matches_but_allows_verified_nonmatches():
    result = rank_recommendations(
        [
            {
                "id": "paneer",
                "title": "Paneer Curry",
                "ingredients": ["paneer", "tomato", "spices"],
                "ingredients_complete": True,
                "base_price": 220,
            },
            {
                "id": "chicken",
                "title": "Chicken Curry",
                "ingredients": ["chicken", "tomato", "spices"],
                "ingredients_complete": True,
                "base_price": 240,
            },
            {
                "id": "unknown",
                "title": "Chef's Special Curry",
                "description": "A house curry",
                "base_price": 210,
            },
        ],
        ai_memories=[{"memory_value": "paneer", "polarity": "dislike"}],
    )

    assert [item["item_id"] for item in result] == ["chicken"]


@pytest.mark.parametrize(
    "ingredient",
    [
        "whey",
        "casein",
        "lard",
        "fish sauce",
        "gelatin",
        "honey",
        "milk",
        "egg",
        "meat",
        "lactose",
        "egg white",
        "albumin",
        "paneer",
        "oyster sauce",
        "bone broth",
    ],
)
def test_vegan_filter_rejects_common_animal_derived_ingredients(ingredient):
    result = rank_recommendations(
        [
            {
                "id": ingredient,
                "title": "Special Bowl",
                "description": "A savory bowl",
                "ingredients": [ingredient],
                "ingredients_complete": True,
                "dietary": ["vegan"],
                "base_price": 180,
            }
        ],
        dietary_preference="vegan",
    )

    assert result == []


@pytest.mark.parametrize(
    "label",
    [
        "non-vegetarian",
        "nonvegetarian",
        "Non Vegetarian",
        "non-veg",
        "nonveg",
        "non veg",
        "animal-based",
        "omnivore",
    ],
)
def test_vegan_filter_rejects_animal_based_dietary_labels(label):
    result = rank_recommendations(
        [
            {
                "id": label,
                "title": "Special Bowl",
                "dietary": ["vegan", label],
                "base_price": 180,
            }
        ],
        dietary_preference="vegan",
    )

    assert result == []


@pytest.mark.parametrize(
    "safe_phrase",
    [
        "almond milk",
        "soy milk",
        "oat milk",
        "plant-based meat",
        "vegan meat",
        "egg-free",
        "dairy-free",
        "non-dairy",
    ],
)
def test_vegan_filter_allows_safe_alternatives_and_free_labels(safe_phrase):
    result = rank_recommendations(
        [
            {
                "id": safe_phrase,
                "title": "Verified Plant Bowl",
                "description": safe_phrase,
                "ingredients": [safe_phrase],
                "ingredients_complete": True,
                "dietary": ["vegan"],
                "base_price": 170,
            }
        ],
        dietary_preference="vegan",
    )

    assert [item["item_id"] for item in result] == [safe_phrase]


def test_safe_alternative_does_not_hide_a_separate_animal_ingredient():
    result = rank_recommendations(
        [
            {
                "id": "oat-milk-whey",
                "title": "Plant Bowl",
                "ingredients": ["oat milk", "whey"],
                "ingredients_complete": True,
                "dietary": ["vegan"],
                "base_price": 170,
            }
        ],
        dietary_preference="vegan",
    )

    assert result == []


def test_vegetarian_label_alone_does_not_establish_vegan_safety():
    result = rank_recommendations(
        [
            {
                "id": "vegetarian-unknown",
                "title": "Vegetarian Special",
                "dietary": ["vegetarian"],
                "base_price": 180,
            }
        ],
        dietary_preference="vegan",
    )

    assert result == []


def test_vegan_filter_uses_complete_ingredients_and_avoids_substring_matches():
    result = rank_recommendations(
        [
            {
                "id": "verified-plant-based",
                "title": "Garden Bowl",
                "ingredients": ["eggplant", "butterfly pea", "chickpeas"],
                "ingredients_complete": True,
                "dietary": ["vegetarian"],
                "base_price": 160,
            }
        ],
        dietary_preference="vegan",
    )

    assert [item["item_id"] for item in result] == ["verified-plant-based"]
