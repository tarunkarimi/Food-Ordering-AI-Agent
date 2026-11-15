"""Database-independent ordering intelligence and reorder safety tests."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.services import ordering_intelligence
from src.services.order_history import (
    list_order_history,
    resolve_unique_order_subdomain,
)
from src.services.ordering_intelligence import (
    build_ordering_intelligence,
    build_smart_reorder_suggestions,
    filter_reorder_suggestions_to_menu,
)
from src.services.reorder import get_reorder_items, validate_reorder_items


def _order(
    items, *, days_ago=0, status="confirmed", order_id="order",
    subdomain="sample", restaurant_name="Sample Kitchen",
):
    return SimpleNamespace(
        order_id=order_id,
        user_id=7,
        restaurant_name=restaurant_name,
        subdomain=subdomain,
        status=status,
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        items_json=json.dumps(items),
    )


def test_ordering_intelligence_counts_orders_once_and_tracks_recency(monkeypatch):
    orders = [
        _order(
            [
                {"item_id": "curry", "title": "Curry", "quantity": 2},
                {"item_id": "curry", "title": "Curry", "quantity": 1},
            ],
            days_ago=1,
            order_id="new",
        ),
        _order(
            [{"item_id": "curry", "title": "Curry", "quantity": 1}],
            days_ago=30,
            order_id="old",
        ),
        _order(
            [{"item_id": "failed", "title": "Failed Order Item", "quantity": 1}],
            status="cancelled",
            order_id="cancelled",
        ),
    ]
    monkeypatch.setattr(
        ordering_intelligence,
        "list_order_history",
        lambda db, user_id, limit, offset, **kwargs: orders,
    )
    monkeypatch.setattr(
        ordering_intelligence,
        "resolve_unique_order_subdomain",
        lambda db, user_id: "sample",
    )

    result = build_ordering_intelligence(object(), user_id=7)

    favorite = result["usual_items"][0]
    assert result["orders_analyzed"] == 2
    assert favorite["order_count"] == 2
    assert favorite["total_quantity"] == 4
    assert favorite["last_order_quantity"] == 3
    assert favorite["last_ordered_at"] == orders[0].created_at
    assert all(item["title"] != "Failed Order Item" for item in result["usual_items"])


def test_smart_reorder_distinguishes_repeat_favorite_and_one_time_purchase(
    monkeypatch,
):
    orders = [
        _order([{"item_id": "repeat", "title": "Repeat", "quantity": 1}], days_ago=120),
        _order([{"item_id": "repeat", "title": "Repeat", "quantity": 1}], days_ago=100),
        _order([{"item_id": "once", "title": "Once", "quantity": 1}], days_ago=1),
    ]
    monkeypatch.setattr(
        ordering_intelligence,
        "list_order_history",
        lambda db, user_id, limit, offset, **kwargs: orders,
    )
    monkeypatch.setattr(
        ordering_intelligence,
        "resolve_unique_order_subdomain",
        lambda db, user_id: "sample",
    )
    reference_time = datetime.now(timezone.utc)

    suggestions = build_smart_reorder_suggestions(
        object(), user_id=7, now=reference_time
    )

    assert suggestions[0]["title"] == "Repeat"
    assert suggestions[0]["frequency_type"] == "repeat_favorite"
    assert suggestions[0]["order_count"] == 2
    once = next(item for item in suggestions if item["title"] == "Once")
    assert once["frequency_type"] == "one_time"
    assert "Previously ordered once" in once["reason"]


def test_reorder_suggestions_require_live_menu_identity_and_current_price():
    suggestions = [
        {"item_id": "1", "title": "Current Curry", "order_count": 3},
        {"item_id": "2", "title": "Removed Soup", "order_count": 2},
        {"item_id": "3", "title": "Sold Out Rice", "order_count": 2},
        {"item_id": "4", "title": "No Price", "order_count": 2},
        {"item_id": "5", "title": "Renamed Item", "order_count": 2},
    ]
    menu = [
        {"id": "1", "title": "Current Curry", "base_price": 270},
        {"id": "3", "title": "Sold Out Rice", "base_price": 80, "available": False},
        {"id": "4", "title": "No Price"},
        {"id": "5", "title": "New Item Name", "base_price": 125},
    ]

    result = filter_reorder_suggestions_to_menu(suggestions, menu)

    assert result == [
        {
            "item_id": "1",
            "title": "Current Curry",
            "order_count": 3,
            "current_price": 270.0,
        }
    ]


@pytest.mark.parametrize(
    ("availability", "expected"),
    [(True, True), (False, False), ("true", False), (None, False)],
)
def test_reorder_availability_flags_are_validated(availability, expected):
    menu_item = {
        "id": "1", "title": "Curry", "base_price": 100,
        "available": availability,
    }
    assert ordering_intelligence.is_menu_item_available(menu_item) is expected


def test_reorder_missing_availability_uses_current_catalog_contract():
    # The menu API returns current catalog entries and its order endpoint
    # rejects items absent from that catalog; membership is availability evidence.
    assert ordering_intelligence.is_menu_item_available(
        {"id": "1", "title": "Curry", "base_price": 100}
    ) is True


def test_order_history_signals_are_scoped_by_tenant(monkeypatch):
    orders = [
        _order([{"item_id": "same-id", "title": "Same Dish"}], subdomain="tenant-a"),
        _order([{"item_id": "same-id", "title": "Same Dish"}], subdomain="tenant-b"),
    ]
    monkeypatch.setattr(
        ordering_intelligence,
        "list_order_history",
        lambda db, user_id, limit, offset, **kwargs: orders,
    )

    result = build_ordering_intelligence(
        object(), user_id=7, restaurant_name="Sample Kitchen", subdomain="tenant-a"
    )
    assert result["orders_analyzed"] == 1
    assert result["usual_items"][0]["order_count"] == 1


@pytest.mark.parametrize("resolved", [None, ""])
def test_missing_or_ambiguous_tenant_returns_empty_profile(monkeypatch, resolved):
    monkeypatch.setattr(
        ordering_intelligence,
        "resolve_unique_order_subdomain",
        lambda db, user_id: resolved,
    )
    monkeypatch.setattr(
        ordering_intelligence,
        "list_order_history",
        lambda *args, **kwargs: pytest.fail("ambiguous history must not be loaded"),
    )

    result = build_ordering_intelligence(object(), user_id=7)

    assert result["orders_analyzed"] == 0
    assert result["usual_items"] == []


def test_explicit_tenant_bypasses_ambiguous_tenant_resolution(monkeypatch):
    queried = []
    monkeypatch.setattr(
        ordering_intelligence,
        "resolve_unique_order_subdomain",
        lambda *args, **kwargs: pytest.fail("explicit tenant is authoritative"),
    )
    monkeypatch.setattr(
        ordering_intelligence,
        "list_order_history",
        lambda db, user_id, limit, offset, **kwargs: queried.append(kwargs) or [
            _order([{"item_id": "curry", "title": "Curry"}], subdomain="tenant-a")
        ],
    )

    result = build_ordering_intelligence(
        object(), user_id=7, subdomain="tenant-a"
    )

    assert queried == [{"subdomain": "tenant-a"}]
    assert result["usual_items"][0]["order_count"] == 1


def test_order_history_query_applies_tenant_filter_before_limit():
    class QueryOnlySession:
        statement = None

        def scalars(self, statement):
            self.statement = statement
            return []

    db = QueryOnlySession()
    assert list_order_history(
        db,
        user_id=7,
        limit=20,
        subdomain="tenant-a",
        restaurant_name="Shared Name",
    ) == []
    values = db.statement.compile().params.values()
    assert 7 in values
    assert "tenant-a" in values
    assert "Shared Name" in values


@pytest.mark.parametrize(
    ("values", "expected"),
    [(["tenant-a"], "tenant-a"), (["tenant-a", "tenant-b"], None), (["   "], None), ([], None)],
)
def test_resolve_unique_order_subdomain_fails_closed(values, expected):
    class Result:
        def all(self):
            return values

    class QueryOnlySession:
        statement = None

        def scalars(self, statement):
            self.statement = statement
            return Result()

    db = QueryOnlySession()
    assert resolve_unique_order_subdomain(db, user_id=7) == expected
    params = db.statement.compile().params
    assert 7 in params.values()


def test_reorder_lookup_is_scoped_to_the_authenticated_user():
    class QueryOnlySession:
        statement = None

        def scalar(self, statement):
            self.statement = statement
            return None

    db = QueryOnlySession()
    with pytest.raises(LookupError, match="Order not found"):
        get_reorder_items(db, user_id=777, order_id="synthetic-order")

    params = db.statement.compile().params
    assert 777 in params.values()
    assert "synthetic-order" in params.values()


def test_reorder_validation_uses_current_price_and_rejects_unavailable_items(
    monkeypatch,
):
    monkeypatch.setattr(
        "src.services.reorder._fetch_menu_items_for_tenant",
        lambda state: (
            [{"id": "current", "title": "Curry", "base_price": 275, "variations": []}],
            None,
        ),
    )
    validated = validate_reorder_items(
        subdomain="sample",
        items=[
            {
                "item_id": "current",
                "title": "Curry",
                "quantity": 2,
                "base_price": 99,
                "variation": None,
            }
        ],
    )
    assert validated[0]["unit_price"] == 275

    monkeypatch.setattr(
        "src.services.reorder._fetch_menu_items_for_tenant",
        lambda state: ([{
            "id": "current", "title": "Curry", "base_price": 275,
            "variations": [], "available": "unknown",
        }], None),
    )
    with pytest.raises(LookupError, match="no longer available"):
        validate_reorder_items(
            subdomain="sample",
            items=[{"item_id": "current", "title": "Curry", "quantity": 1}],
        )

    with pytest.raises(LookupError, match="no longer available"):
        validate_reorder_items(
            subdomain="sample",
            items=[
                {
                    "item_id": "historical-only",
                    "title": "Old Curry",
                    "quantity": 1,
                    "variation": None,
                }
            ],
        )
