"""Database-independent tests for tenant verification before reorder writes."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.agents.tools import cart as cart_tools
from src.api.routes import reorder as reorder_route
from src.db.models.cart import Cart
from src.services import reorder as reorder_service


HISTORICAL_ORDER = {
    "order_id": "synthetic-order",
    "restaurant_name": "Shared Kitchen",
    "subdomain": "tenant-a",
    "status": "confirmed",
    "items": [{
        "item_id": "item-1",
        "title": "Current Curry",
        "quantity": 2,
        "variation": None,
    }],
}


def _menu_envelope(subdomain="tenant-a"):
    result = {
        "restaurant_name": "Shared Kitchen",
        "items": [{
            "id": "item-1",
            "title": "Current Curry",
            "base_price": 175,
            "variations": [],
        }],
    }
    if subdomain is not None:
        result["subdomain"] = subdomain
    return result


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _prepare_route(monkeypatch, menu_payload):
    writes = []
    monkeypatch.setattr(
        reorder_route,
        "get_reorder_items",
        lambda db, *, user_id, order_id: HISTORICAL_ORDER,
    )
    monkeypatch.setattr(
        cart_tools,
        "request_read_with_retry",
        lambda request: request(),
    )
    monkeypatch.setattr(
        cart_tools.requests,
        "get",
        lambda url, timeout: _Response(menu_payload),
    )
    monkeypatch.setattr(
        reorder_route,
        "add_reorder_items_to_cart",
        lambda db, **kwargs: writes.append(kwargs) or object(),
    )
    monkeypatch.setattr(reorder_route, "_serialize_cart", lambda cart: {"items": []})
    return writes


def test_explicit_reorder_accepts_matching_menu_tenant_and_uses_current_price(
    monkeypatch,
):
    writes = _prepare_route(monkeypatch, _menu_envelope())

    result = reorder_route.reorder_order(
        "synthetic-order",
        auth=SimpleNamespace(user=SimpleNamespace(id=41)),
        db=object(),
    )

    assert result["success"] is True
    assert result["items"][0]["unit_price"] == 175
    assert len(writes) == 1
    assert writes[0]["user_id"] == 41
    assert writes[0]["subdomain"] == "tenant-a"


@pytest.mark.parametrize(
    "payload",
    [
        _menu_envelope("tenant-b"),
        _menu_envelope(None),
        {**_menu_envelope(), "subdomain": "   "},
        {**_menu_envelope(), "items": "malformed"},
        ["malformed-envelope"],
    ],
    ids=["mismatched", "missing", "blank", "malformed-items", "malformed-envelope"],
)
def test_explicit_reorder_rejects_unverified_tenant_before_cart_write(
    monkeypatch, payload,
):
    writes = _prepare_route(monkeypatch, payload)

    with pytest.raises(HTTPException) as error:
        reorder_route.reorder_order(
            "synthetic-order",
            auth=SimpleNamespace(user=SimpleNamespace(id=41)),
            db=object(),
        )

    assert error.value.status_code == 503
    assert "not added to your cart" in error.value.detail
    assert "tenant-b" not in error.value.detail
    assert writes == []


def test_reorder_cart_retry_sets_historical_quantity_instead_of_accumulating(
    monkeypatch,
):
    cart = Cart(
        user_id=41,
        restaurant_name="Shared Kitchen",
        subdomain="tenant-a",
        items=[],
    )

    class FakeDb:
        def add(self, item):
            return None

        def commit(self):
            return None

    db = FakeDb()
    monkeypatch.setattr(
        reorder_service,
        "get_or_create_cart",
        lambda *args, **kwargs: cart,
    )
    monkeypatch.setattr(reorder_service, "_reload_cart", lambda db, user_id: cart)
    item = {
        "item_key": "item-1|no_variant",
        "item_id": "item-1",
        "title": "Current Curry",
        "quantity": 2,
        "unit_price": 175,
        "variation_id": None,
        "variation_name": None,
        "variation_price": None,
    }

    for _ in range(3):
        reorder_service.add_reorder_items_to_cart(
            db,
            user_id=41,
            restaurant_name="Shared Kitchen",
            subdomain="tenant-a",
            items=[item],
        )

    assert len(cart.items) == 1
    assert cart.items[0].quantity == 2
