"""Database-independent tests for tenant-scoped persistent profiles."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.api.routes import persistent_ordering_intelligence as profile_route
from src.services import persistent_ordering_intelligence as profile_service
from src.services.persistent_ordering_intelligence import (
    _resolve_unique_ordering_subdomain,
)


def _order(*, tenant: str, order_id: str, subtotal: int, quantity: int):
    return SimpleNamespace(
        user_id=41,
        subdomain=tenant,
        restaurant_name="Shared Kitchen",
        status="confirmed",
        order_id=order_id,
        subtotal=subtotal,
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        items_json=(
            '[{"item_id":"same-item","title":"Same Dish",'
            f'"quantity":{quantity}}}]'
        ),
    )


def test_explicit_tenant_profile_separates_duplicate_restaurant_names(monkeypatch):
    tenant_a = _order(tenant="tenant-a", order_id="A-1", subtotal=100, quantity=2)
    tenant_b = _order(tenant="tenant-b", order_id="B-1", subtotal=900, quantity=9)
    loaded = []

    def load_orders(db, *, user_id, subdomain, restaurant_name):
        loaded.append((user_id, subdomain, restaurant_name))
        return [tenant_a] if subdomain == "tenant-a" else [tenant_b]

    monkeypatch.setattr(profile_service, "_load_tenant_order_history", load_orders)
    monkeypatch.setattr(
        profile_service,
        "_resolve_unique_ordering_subdomain",
        lambda db, **kwargs: pytest.fail("explicit tenant should not be inferred"),
    )

    profile = profile_service.get_persistent_ordering_profile(
        object(),
        user_id=41,
        restaurant_name="Shared Kitchen",
        subdomain="tenant-a",
    )

    assert loaded == [(41, "tenant-a", "Shared Kitchen")]
    assert profile["total_orders"] == 1
    assert profile["total_spend"] == 100.0
    assert profile["favorite_items"][0]["total_quantity"] == 2


def test_missing_tenant_uses_only_one_unambiguous_history_tenant(monkeypatch):
    observed = []
    monkeypatch.setattr(
        profile_service,
        "_resolve_unique_ordering_subdomain",
        lambda db, *, user_id: "tenant-b",
    )
    monkeypatch.setattr(
        profile_service,
        "_load_tenant_order_history",
        lambda db, **kwargs: observed.append(kwargs)
        or [_order(tenant="tenant-b", order_id="B-1", subtotal=900, quantity=9)],
    )

    profile = profile_service.get_persistent_ordering_profile(
        object(), user_id=41, restaurant_name="Shared Kitchen"
    )

    assert observed == [{
        "user_id": 41,
        "subdomain": "tenant-b",
        "restaurant_name": "Shared Kitchen",
    }]
    assert profile["total_spend"] == 900.0


@pytest.mark.parametrize(
    "tenant_values",
    [[], ["", None], ["   "], ["tenant-a", "tenant-b"]],
    ids=["no-history", "blank-history", "whitespace-history", "ambiguous-history"],
)
def test_missing_ambiguous_tenant_returns_safe_empty_profile(
    monkeypatch, tenant_values,
):
    class Result:
        def all(self):
            return tenant_values

    class QueryOnlySession:
        statement = None

        def scalars(self, statement):
            self.statement = statement
            return Result()

    db = QueryOnlySession()
    monkeypatch.setattr(
        profile_service,
        "_load_tenant_order_history",
        lambda *args, **kwargs: pytest.fail("ambiguous tenant history was loaded"),
    )

    profile = profile_service.get_persistent_ordering_profile(
        db, user_id=41, restaurant_name="Shared Kitchen"
    )

    compiled = db.statement.compile()
    query_params = compiled.params.values()
    assert 41 in query_params
    assert "Shared Kitchen" not in query_params
    assert profile["user_id"] == 41
    assert profile["total_orders"] == 0
    assert profile["total_spend"] == 0.0
    assert profile["favorite_items"] == []
    assert profile["favorite_restaurants"] == []


def test_resolver_uses_one_distinct_subdomain_for_all_user_history():
    class Result:
        def all(self):
            return ["tenant-a"]

    class QueryOnlySession:
        statement = None

        def scalars(self, statement):
            self.statement = statement
            return Result()

    db = QueryOnlySession()
    assert _resolve_unique_ordering_subdomain(db, user_id=41) == "tenant-a"
    compiled = db.statement.compile()
    assert 41 in compiled.params.values()
    assert "Shared Kitchen" not in compiled.params.values()


@pytest.mark.parametrize("explicit_tenant", ["", "   ", " tenant-a "])
def test_invalid_explicit_tenant_does_not_fall_back_to_history(
    monkeypatch, explicit_tenant,
):
    monkeypatch.setattr(
        profile_service,
        "_resolve_unique_ordering_subdomain",
        lambda *args, **kwargs: pytest.fail("invalid explicit tenant is not omitted"),
    )
    monkeypatch.setattr(
        profile_service,
        "_load_tenant_order_history",
        lambda *args, **kwargs: pytest.fail("invalid tenant must not load history"),
    )

    context = profile_service.build_persistent_ai_ordering_context(
        object(),
        user_id=41,
        subdomain=explicit_tenant,
    )

    assert context["ordering_history"]["total_orders"] == 0
    assert context["favorite_items"] == []


@pytest.mark.parametrize(
    "restaurants",
    [
        ["Shared Kitchen", "Shared Kitchen"],
        ["North Cafe", "South Cafe"],
    ],
    ids=["same-display-name", "different-display-names"],
)
def test_multiple_tenants_are_ambiguous_regardless_of_display_names(
    restaurants,
):
    class Result:
        def all(self):
            return ["tenant-a", "tenant-b"]

    class QueryOnlySession:
        def scalars(self, statement):
            self.statement = statement
            return Result()

    db = QueryOnlySession()
    profile = profile_service.get_persistent_ordering_profile(
        db,
        user_id=41,
        restaurant_name=restaurants[0],
    )

    assert profile["total_orders"] == 0
    assert profile["favorite_items"] == []
    assert profile["favorite_restaurants"] == []
    assert "restaurant_name" not in str(db.statement).lower()


def test_profile_route_passes_requested_subdomain(monkeypatch):
    class SessionContext:
        def __enter__(self):
            return "mock-db"

        def __exit__(self, *args):
            return False

    observed = {}
    monkeypatch.setattr(profile_route, "SessionLocal", SessionContext)
    monkeypatch.setattr(
        profile_route,
        "get_persistent_ordering_profile",
        lambda db, **kwargs: observed.update(db=db, **kwargs) or {"ok": True},
    )

    result = profile_route.persistent_ordering_intelligence(
        restaurant_name="Shared Kitchen",
        subdomain="tenant-a",
        session=SimpleNamespace(user=SimpleNamespace(id=41)),
    )

    assert result == {"ok": True}
    assert observed == {
        "db": "mock-db",
        "user_id": 41,
        "restaurant_name": "Shared Kitchen",
        "subdomain": "tenant-a",
    }
