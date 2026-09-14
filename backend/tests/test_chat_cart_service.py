"""Chat cart service regression tests."""

import pytest

from src.agents.state import Cart
from src.services.chat_cart import (
    add_to_cart,
    build_authoritative_unit,
    build_session_config,
    find_menu_item,
    remove_from_cart,
)


def test_build_session_config_is_user_isolated():
    assert build_session_config("abc", user_id=42) == {
        "configurable": {
            "thread_id": "user:42:session:abc",
        }
    }


def test_build_session_config_strips_session_id():
    assert build_session_config("  abc  ") == {
        "configurable": {
            "thread_id": "abc",
        }
    }


def test_find_menu_item_requires_id_and_title():
    items = [
        {"id": "1", "title": "Pizza"},
        {"id": "2", "title": "Burger"},
    ]

    assert find_menu_item(items, "1", "Pizza")["title"] == "Pizza"
    assert find_menu_item(items, "1", "Burger") is None


def test_build_authoritative_unit_uses_menu_price():
    unit = build_authoritative_unit(
        {
            "id": "1",
            "title": "Pizza",
            "base_price": 250,
            "variations": [],
        },
        "1",
        2,
        None,
    )

    assert unit.quantity == 2
    assert unit.base_price == 250
    assert unit.key == "1|no_variant"
    assert unit.variation is None


def test_build_authoritative_unit_uses_selected_variation_price():
    unit = build_authoritative_unit(
        {
            "id": "1",
            "title": "Pizza",
            "base_price": 250,
            "variations": [
                {
                    "id": "large",
                    "name": "Large",
                    "price": "325",
                }
            ],
        },
        "1",
        1,
        "large",
    )

    assert unit.base_price == 325
    assert unit.key == "1|large"
    assert unit.variation.id == "large"


def test_add_to_cart_merges_same_unit():
    menu_item = {
        "id": "1",
        "title": "Pizza",
        "base_price": 250,
        "variations": [],
    }

    cart = add_to_cart(Cart(items=[]), menu_item, 2, None)
    cart = add_to_cart(cart, menu_item, 3, None)

    assert len(cart.items) == 1
    assert len(cart.items[0].units) == 1
    assert cart.items[0].units[0].quantity == 5


def test_remove_from_cart_removes_requested_quantity():
    menu_item = {
        "id": "1",
        "title": "Pizza",
        "base_price": 250,
        "variations": [],
    }

    cart = add_to_cart(Cart(items=[]), menu_item, 5, None)
    cart = remove_from_cart(cart, "1", "Pizza", 2, None)

    assert cart.items[0].units[0].quantity == 3


def test_remove_from_cart_removes_unit_at_exact_quantity():
    menu_item = {
        "id": "1",
        "title": "Pizza",
        "base_price": 250,
        "variations": [],
    }

    cart = add_to_cart(Cart(items=[]), menu_item, 2, None)
    cart = remove_from_cart(cart, "1", "Pizza", 2, None)

    assert cart.items == []


def test_remove_from_cart_rejects_missing_item():
    with pytest.raises(ValueError, match="not found in cart"):
        remove_from_cart(
            Cart(items=[]),
            "missing",
            "Missing",
            1,
            None,
        )
