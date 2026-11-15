from src.services.recommendation_ranking import rank_recommendations


def test_persistent_favorite_item_gets_strong_ranking_boost():
    menu = [
        {
            "id": "new-1",
            "title": "Paneer Biryani",
            "base_price": 250,
            "category": "Biryani",
        },
        {
            "id": "fav-1",
            "title": "Chicken Biryani",
            "base_price": 280,
            "category": "Biryani",
        },
    ]

    persistent_context = {
        "favorite_items": [
            {
                "item_key": "fav-1",
                "item_title": "Chicken Biryani",
                "restaurant_name": "Andhra Kitchen",
                "order_count": 8,
                "total_quantity": 12,
            }
        ],
        "favorite_restaurants": [],
    }

    results = rank_recommendations(
        menu,
        persistent_context=persistent_context,
        current_restaurant="Andhra Kitchen",
        limit=5,
    )

    assert results[0]["title"] == "Chicken Biryani"
    assert results[0]["score"] > results[1]["score"]
    assert any(
        "frequently ordered" in reason
        for reason in results[0]["reasons"]
    )


def test_persistent_favorite_restaurant_boosts_current_menu_items():
    menu = [
        {
            "id": "item-1",
            "title": "Chicken Biryani",
            "base_price": 250,
        },
        {
            "id": "item-2",
            "title": "Paneer Rice",
            "base_price": 200,
        },
    ]

    persistent_context = {
        "favorite_items": [],
        "favorite_restaurants": [
            {
                "restaurant_name": "Andhra Kitchen",
                "order_count": 6,
                "total_spend": 2400,
            }
        ],
    }

    results = rank_recommendations(
        menu,
        persistent_context=persistent_context,
        current_restaurant="Andhra Kitchen",
        limit=5,
    )

    assert len(results) == 2
    assert all(
        "frequently order from this restaurant" in reason
        for result in results
        for reason in result["reasons"]
    )


def test_persistent_context_does_not_override_budget():
    menu = [
        {
            "id": "fav-1",
            "title": "Chicken Biryani",
            "base_price": 500,
        },
        {
            "id": "cheap-1",
            "title": "Chicken Rice",
            "base_price": 180,
        },
    ]

    persistent_context = {
        "favorite_items": [
            {
                "item_key": "fav-1",
                "item_title": "Chicken Biryani",
                "restaurant_name": "Andhra Kitchen",
                "order_count": 100,
                "total_quantity": 200,
            }
        ],
        "favorite_restaurants": [],
    }

    results = rank_recommendations(
        menu,
        persistent_context=persistent_context,
        current_restaurant="Andhra Kitchen",
        max_price=300,
        limit=5,
    )

    assert len(results) == 1
    assert results[0]["title"] == "Chicken Rice"


def test_persistent_context_does_not_override_dietary_filter():
    menu = [
        {
            "id": "fav-1",
            "title": "Chicken Biryani",
            "base_price": 250,
            "description": "chicken biryani",
        },
        {
            "id": "veg-1",
            "title": "Paneer Biryani",
            "base_price": 240,
            "description": "vegetarian paneer biryani",
            "dietary": ["vegetarian"],
        },
    ]

    persistent_context = {
        "favorite_items": [
            {
                "item_key": "fav-1",
                "item_title": "Chicken Biryani",
                "restaurant_name": "Andhra Kitchen",
                "order_count": 100,
                "total_quantity": 200,
            }
        ],
        "favorite_restaurants": [],
    }

    results = rank_recommendations(
        menu,
        persistent_context=persistent_context,
        current_restaurant="Andhra Kitchen",
        dietary_preference="vegetarian",
        limit=5,
    )

    assert len(results) == 1
    assert results[0]["title"] == "Paneer Biryani"


def test_without_persistent_context_ranking_remains_backward_compatible():
    menu = [
        {
            "id": "item-1",
            "title": "Chicken Biryani",
            "base_price": 250,
            "category": "Biryani",
        },
        {
            "id": "item-2",
            "title": "Paneer Rice",
            "base_price": 200,
            "category": "Rice",
        },
    ]

    results_without_context = rank_recommendations(
        menu,
        limit=5,
    )

    results_with_empty_context = rank_recommendations(
        menu,
        persistent_context={},
        limit=5,
    )

    assert results_without_context == results_with_empty_context
