"""Isolated tests for current-menu validation of reorder suggestions."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api.routes import ordering_intelligence as ordering_route
from src.agents.tools import cart as cart_tools


def _order(*, tenant="sample", name="Sample Kitchen"):
    return SimpleNamespace(
        restaurant_name=name,
        subdomain=tenant,
        status="confirmed",
        created_at=datetime.now(timezone.utc),
    )


def test_route_scopes_history_by_user_and_shows_current_menu_price(monkeypatch):
    user_ids = []
    monkeypatch.setattr(
        ordering_route,
        "list_order_history",
        lambda db, user_id, limit, offset, **kwargs: user_ids.append(user_id) or [_order()],
    )
    monkeypatch.setattr(ordering_route, "resolve_unique_order_subdomain", lambda db, user_id: "sample")
    monkeypatch.setattr(
        ordering_route,
        "_fetch_menu_items_for_tenant",
        lambda subdomain: ([{"id": "curry", "title": "Curry", "base_price": 310}], None),
    )
    monkeypatch.setattr(
        ordering_route,
        "build_smart_reorder_suggestions",
        lambda db, user_id, restaurant_name, limit, subdomain: [
            {"item_id": "curry", "title": "Curry", "order_count": 2}
        ],
    )

    response = ordering_route.get_reorder_suggestions(
        restaurant_name=None,
        subdomain=None,
        limit=5,
        auth=SimpleNamespace(user=SimpleNamespace(id=77)),
        db=object(),
    )

    assert user_ids == [77]
    assert response["suggestions"][0]["current_price"] == 310


def test_route_does_not_present_historical_suggestions_when_menu_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        ordering_route,
        "list_order_history",
        lambda db, user_id, limit, offset, **kwargs: [_order()],
    )
    monkeypatch.setattr(ordering_route, "resolve_unique_order_subdomain", lambda db, user_id: "sample")
    monkeypatch.setattr(
        ordering_route,
        "_fetch_menu_items_for_tenant",
        lambda subdomain: ([], "unavailable"),
    )

    with pytest.raises(HTTPException) as error:
        ordering_route.get_reorder_suggestions(
            restaurant_name=None,
        subdomain=None,
            limit=5,
            auth=SimpleNamespace(user=SimpleNamespace(id=77)),
            db=object(),
        )

    assert error.value.status_code == 503


def test_duplicate_display_names_without_tenant_fail_closed(monkeypatch):
    orders = [_order(tenant="tenant-b"), _order(tenant="tenant-a")]
    menu_tenants = []
    builder_tenants = []
    monkeypatch.setattr(
        ordering_route,
        "list_order_history",
        lambda db, user_id, limit, offset, **kwargs: orders,
    )
    monkeypatch.setattr(ordering_route, "resolve_unique_order_subdomain", lambda db, user_id: None)
    monkeypatch.setattr(
        ordering_route,
        "_fetch_menu_items_for_tenant",
        lambda subdomain: menu_tenants.append(subdomain)
        or ([{"id": "curry", "title": "Curry", "base_price": 200}], None),
    )
    monkeypatch.setattr(
        ordering_route,
        "build_smart_reorder_suggestions",
        lambda db, user_id, restaurant_name, limit, subdomain:
        builder_tenants.append(subdomain)
        or [{"item_id": "curry", "title": "Curry", "order_count": 2}],
    )

    response = ordering_route.get_reorder_suggestions(
        restaurant_name="Sample Kitchen",
        subdomain=None,
        limit=5,
        auth=SimpleNamespace(user=SimpleNamespace(id=77)),
        db=object(),
    )
    assert response == {"suggestions": []}
    assert menu_tenants == []
    assert builder_tenants == []


def test_duplicate_display_names_with_explicit_tenant_stay_scoped(monkeypatch):
    menu_tenants = []
    builder_tenants = []
    orders = [_order(tenant="tenant-b"), _order(tenant="tenant-a")]
    monkeypatch.setattr(ordering_route, "list_order_history", lambda *args, **kwargs: orders)
    monkeypatch.setattr(
        ordering_route,
        "_fetch_menu_items_for_tenant",
        lambda subdomain: menu_tenants.append(subdomain)
        or ([{"id": "curry", "title": "Curry", "base_price": 200}], None),
    )
    monkeypatch.setattr(
        ordering_route,
        "build_smart_reorder_suggestions",
        lambda db, user_id, restaurant_name, limit, subdomain:
        builder_tenants.append(subdomain)
        or [{"item_id": "curry", "title": "Curry", "order_count": 2}],
    )

    response = ordering_route.get_reorder_suggestions(
        restaurant_name="Sample Kitchen", subdomain="tenant-a", limit=5,
        auth=SimpleNamespace(user=SimpleNamespace(id=77)), db=object(),
    )

    assert response["suggestions"][0]["current_price"] == 200
    assert menu_tenants == ["tenant-a"]
    assert builder_tenants == ["tenant-a"]


@pytest.mark.parametrize(
    ("menu", "expected_error"),
    [
        ({"restaurant_name": "Shared Kitchen", "subdomain": "tenant-a", "items": []}, None),
        ({"restaurant_name": "Shared Kitchen", "subdomain": "tenant-b", "items": []}, "different restaurant"),
        ({"restaurant_name": "Shared Kitchen", "subdomain": " tenant-a ", "items": []}, "different restaurant"),
        ({"restaurant_name": "Shared Kitchen", "items": []}, "invalid restaurant identity"),
        ({"restaurant_name": "Shared Kitchen", "subdomain": "  ", "items": []}, "invalid restaurant identity"),
        ({"subdomain": "tenant-a", "items": "malformed"}, "invalid response"),
    ],
)
def test_menu_tenant_envelope_is_verified_before_items_are_used(
    monkeypatch, menu, expected_error,
):
    requested_urls = []

    class FakeResponse:
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
        lambda url, timeout: requested_urls.append(url) or FakeResponse(),
    )

    items, error = cart_tools._fetch_menu_items_for_tenant("tenant-a")

    assert "?subdomain=tenant-a" in requested_urls[0]
    if expected_error:
        assert items == []
        assert expected_error in error
    else:
        assert items == []
        assert error is None


def test_route_rejects_wrong_menu_tenant_without_returning_suggestions(monkeypatch):
    monkeypatch.setattr(
        ordering_route,
        "list_order_history",
        lambda db, user_id, limit, offset, **kwargs: [_order(tenant="tenant-a")],
    )
    monkeypatch.setattr(
        ordering_route,
        "_fetch_menu_items_for_tenant",
        lambda subdomain: ([], "The menu service returned a different restaurant menu."),
    )
    builder_called = False

    def build_suggestions(*args, **kwargs):
        nonlocal builder_called
        builder_called = True
        return [{"item_id": "curry", "title": "Curry"}]

    monkeypatch.setattr(ordering_route, "build_smart_reorder_suggestions", build_suggestions)
    with pytest.raises(HTTPException) as error:
        ordering_route.get_reorder_suggestions(
            restaurant_name=None,
            subdomain="tenant-a",
            limit=5,
            auth=SimpleNamespace(user=SimpleNamespace(id=77)),
            db=object(),
        )
    assert error.value.status_code == 503
    assert builder_called is False
