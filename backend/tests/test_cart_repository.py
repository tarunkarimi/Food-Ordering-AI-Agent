"""Cart repository unit tests."""

from unittest.mock import Mock

from src.db.models import Cart, CartItem
from src.repositories.cart_repository import (
    add_cart_item,
    create_cart,
    delete_all_cart_items,
    delete_cart_item,
    get_cart_item,
)


def test_create_cart_adds_and_flushes_cart():
    db = Mock()

    cart = create_cart(
        db,
        user_id=123,
        restaurant_name="Test Restaurant",
        subdomain="test",
    )

    assert isinstance(cart, Cart)
    assert cart.user_id == 123
    assert cart.restaurant_name == "Test Restaurant"
    assert cart.subdomain == "test"
    db.add.assert_called_once_with(cart)
    db.flush.assert_called_once()


def test_get_cart_item_returns_matching_item():
    cart = Cart(
        user_id=123,
        restaurant_name="Test Restaurant",
        subdomain="test",
    )

    first = CartItem(
        item_key="first",
        item_id="1",
        title="First",
        quantity=1,
        unit_price=10,
    )
    second = CartItem(
        item_key="second",
        item_id="2",
        title="Second",
        quantity=1,
        unit_price=20,
    )

    cart.items = [first, second]

    assert get_cart_item(
        cart,
        item_key="second",
    ) is second


def test_get_cart_item_returns_none_for_missing_item():
    cart = Cart(
        user_id=123,
        restaurant_name="Test Restaurant",
        subdomain="test",
    )

    assert get_cart_item(
        cart,
        item_key="missing",
    ) is None


def test_add_cart_item_adds_new_item():
    db = Mock()

    cart = Cart(
        user_id=123,
        restaurant_name="Test Restaurant",
        subdomain="test",
    )

    item = add_cart_item(
        db,
        cart=cart,
        item_key="item-1",
        item_id="1",
        title="Burger",
        quantity=2,
        unit_price=150,
        variation_id=None,
        variation_name=None,
        variation_price=None,
    )

    assert isinstance(item, CartItem)
    assert item.item_key == "item-1"
    assert item.quantity == 2
    assert item.unit_price == 150
    db.add.assert_called_once_with(item)


def test_delete_cart_item_delegates_to_session():
    db = Mock()
    item = CartItem()

    delete_cart_item(
        db,
        item=item,
    )

    db.delete.assert_called_once_with(item)


def test_delete_all_cart_items_deletes_current_items():
    db = Mock()

    cart = Cart(
        user_id=123,
        restaurant_name="Test Restaurant",
        subdomain="test",
    )

    first = CartItem(item_key="first")
    second = CartItem(item_key="second")
    cart.items = [first, second]

    delete_all_cart_items(
        db,
        cart=cart,
    )

    assert db.delete.call_count == 2
    db.delete.assert_any_call(first)
    db.delete.assert_any_call(second)
