from fastapi.testclient import TestClient
import pytest
import main as menu_main
from unittest.mock import MagicMock

from main import app
from order_storage import (
    IdempotencyConflict,
    OrderStorageUnavailable,
    PostgresOrderRepository,
    get_order_repository,
    request_fingerprint,
)
from migration_config import MENU_VERSION_TABLE, configure_migration_context


TEST_MENU_SERVICE_KEY = "synthetic-menu-service-key-minimum-32-characters"


def test_menu_migrations_use_an_independent_version_table():
    migration_context = MagicMock()

    configure_migration_context(
        migration_context,
        url="postgresql+psycopg://synthetic/unused",
        target_metadata=None,
    )

    assert MENU_VERSION_TABLE == "menu_backend_alembic_version"
    assert MENU_VERSION_TABLE != "alembic_version"
    assert migration_context.configure.call_args.kwargs["version_table"] == MENU_VERSION_TABLE


class MemoryOrderRepository:
    """Deterministic API-test double; persistence integration tests use PostgreSQL."""

    def __init__(self):
        self.orders = {}
        self.keys = {}

    def health(self):
        return True

    def create_order(self, order):
        scope = (order["user_id"], order["subdomain"], order["idempotency_key"])
        fingerprint = order["request_fingerprint"]
        existing = self.keys.get(scope)
        if existing:
            order_id = existing
            stored, stored_fingerprint = self.orders[order_id]
            if stored_fingerprint != fingerprint:
                raise IdempotencyConflict
            return dict(stored), True
        order_id = f"ORD-{len(self.orders) + 1:032X}"
        stored = {
            "order_id": order_id,
            "restaurant_name": order["restaurant_name"],
            "subdomain": order["subdomain"],
            "items": order["items"],
            "subtotal": order["subtotal"],
            "status": "confirmed",
            "_user_id": order["user_id"],
        }
        self.orders[order_id] = (stored, fingerprint)
        self.keys[scope] = order_id
        return {key: value for key, value in stored.items() if not key.startswith("_")}, False

    def get_idempotent_order(self, *, user_id, subdomain, idempotency_key, fingerprint):
        order_id = self.keys.get((user_id, subdomain, idempotency_key))
        if not order_id:
            return None
        stored, stored_fingerprint = self.orders[order_id]
        if stored_fingerprint != fingerprint:
            raise IdempotencyConflict
        return {key: value for key, value in stored.items() if not key.startswith("_")}

    def get_order(self, order_id, *, user_id, subdomain):
        entry = self.orders.get(order_id)
        if not entry:
            return None
        order = entry[0]
        if order["_user_id"] != user_id or order["subdomain"] != subdomain:
            return None
        return {key: value for key, value in order.items() if not key.startswith("_")}

    def cancel_order(self, order_id, *, user_id, subdomain):
        order = self.get_order(order_id, user_id=user_id, subdomain=subdomain)
        if order is None:
            return None
        stored = self.orders[order_id][0]
        stored["status"] = "cancelled"
        return self.get_order(order_id, user_id=user_id, subdomain=subdomain)


repository = MemoryOrderRepository()
app.dependency_overrides[get_order_repository] = lambda: repository


@pytest.fixture(autouse=True)
def reset_repository():
    repository.orders.clear()
    repository.keys.clear()
    yield
    repository.orders.clear()
    repository.keys.clear()


client = TestClient(
    app,
    headers={
        "X-Menu-Service-Key": TEST_MENU_SERVICE_KEY,
        "Idempotency-Key": "synthetic-checkout-key-0001",
    },
)


def test_storage_health_requires_migrated_menu_schema():
    repository = PostgresOrderRepository.__new__(PostgresOrderRepository)
    connection = MagicMock()
    repository.engine = MagicMock()
    repository.engine.connect.return_value.__enter__.return_value = connection
    # Readiness accepts later migrations while validating the tables this
    # service needs, so a future schema revision does not strand deployments.
    connection.scalar.return_value = "0002_future_menu_migration"

    assert repository.health() is True
    assert connection.execute.call_count == 3
    assert connection.scalar.call_args.args[0].text == (
        "SELECT version_num FROM menu_backend_alembic_version"
    )

    connection.scalar.return_value = None
    with pytest.raises(OrderStorageUnavailable):
        repository.health()


def valid_order():
    return {
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        "user_id": "synthetic-user-001",
        "items": [
            {
                "item_id": "item-001",
                "title": "Chicken Biryani",
                "quantity": 2,
                "base_price": 220.0,
                "variation": {
                    "id": "regular",
                    "name": "Regular",
                    "price": "220",
                },
            }
        ],
    }


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_order_endpoints_reject_unauthenticated_service_calls():
    headers = {"X-Menu-Service-Key": "wrong-service-key"}

    create_response = client.post(
        "/orders",
        json=valid_order(),
        headers=headers,
    )
    assert create_response.status_code == 401
    assert repository.orders == {}

    assert client.get(
        "/orders/ORD-UNKNOWN",
        params={"subdomain": "test", "user_id": "synthetic-user-001"},
        headers=headers,
    ).status_code == 401
    assert client.delete(
        "/orders/ORD-UNKNOWN",
        params={"subdomain": "test", "user_id": "synthetic-user-001"},
        headers=headers,
    ).status_code == 401


def test_order_endpoints_fail_closed_when_service_key_is_not_configured(monkeypatch):
    import main

    monkeypatch.setattr(main, "MENU_SERVICE_API_KEY", "")

    response = client.post("/orders", json=valid_order())

    assert response.status_code == 503
    assert response.json()["detail"] == "Order service authentication is not configured."


def test_valid_menu_request():
    response = client.get(
        "/",
        params={"subdomain": "test"},
    )

    assert response.status_code == 200
    assert response.json()["restaurant_name"] == "Test Restaurant"


def test_valid_order_creation_and_total_calculation():
    response = client.post(
        "/orders",
        json=valid_order(),
    )

    assert response.status_code == 201

    body = response.json()

    assert body["order_id"].startswith("ORD-")
    assert len(body["order_id"]) == len("ORD-") + 32
    assert body["subtotal"] == 440.0
    assert body["status"] == "confirmed"

    assert body["items"][0]["variation"]["id"] == "regular"
    assert body["items"][0]["variation"]["name"] == "Regular"
    assert body["items"][0]["base_price"] == 220.0


def test_large_variation_uses_authoritative_price():
    payload = valid_order()

    payload["items"][0]["quantity"] = 1
    payload["items"][0]["base_price"] = 280.0
    payload["items"][0]["variation"] = {
        "id": "large",
        "name": "Large",
        "price": "280",
    }

    response = client.post(
        "/orders",
        json=payload,
    )

    assert response.status_code == 201

    body = response.json()

    assert body["subtotal"] == 280.0
    assert body["items"][0]["variation"]["id"] == "large"
    assert body["items"][0]["base_price"] == 280.0


def test_large_variation_rejects_wrong_submitted_price():
    payload = valid_order()

    payload["items"][0]["base_price"] = 220.0
    payload["items"][0]["variation"] = {
        "id": "large",
        "name": "Large",
        "price": "280",
    }

    assert (
        client.post(
            "/orders",
            json=payload,
        ).status_code
        == 400
    )


def test_no_variation_item_accepts_order_without_variation():
    payload = valid_order()

    payload["items"][0] = {
        "item_id": "item-003",
        "title": "Masala Dosa",
        "quantity": 2,
        "base_price": 100.0,
        "variation": None,
    }

    response = client.post(
        "/orders",
        json=payload,
    )

    assert response.status_code == 201

    body = response.json()

    assert body["subtotal"] == 200.0
    assert body["items"][0]["variation"] is None
    assert body["items"][0]["base_price"] == 100.0


def test_no_variation_item_rejects_submitted_variation():
    payload = valid_order()

    payload["items"][0] = {
        "item_id": "item-003",
        "title": "Masala Dosa",
        "quantity": 1,
        "base_price": 100.0,
        "variation": {
            "id": "large",
            "name": "Large",
            "price": "100",
        },
    }

    assert (
        client.post(
            "/orders",
            json=payload,
        ).status_code
        == 400
    )


def test_invalid_restaurant():
    payload = valid_order()
    payload["restaurant_name"] = "Wrong Restaurant"

    assert (
        client.post(
            "/orders",
            json=payload,
        ).status_code
        == 400
    )


def test_invalid_item():
    payload = valid_order()
    payload["items"][0]["item_id"] = "item-999"

    assert (
        client.post(
            "/orders",
            json=payload,
        ).status_code
        == 400
    )


def test_invalid_quantity():
    payload = valid_order()
    payload["items"][0]["quantity"] = 0

    assert (
        client.post(
            "/orders",
            json=payload,
        ).status_code
        == 422
    )


def test_negative_quantity_is_rejected():
    payload = valid_order()
    payload["items"][0]["quantity"] = -1

    assert client.post("/orders", json=payload).status_code == 422


def test_explicitly_unavailable_item_cannot_be_ordered(monkeypatch):
    from main import MENUS

    original_items = MENUS["test"]["items"]
    monkeypatch.setitem(
        MENUS["test"],
        "items",
        [{**original_items[0], "available": False}],
    )

    response = client.post("/orders", json=valid_order())

    assert response.status_code == 409
    assert response.json()["detail"] == "Menu item is not currently available"


def test_invalid_price():
    payload = valid_order()
    payload["items"][0]["base_price"] = 1.0

    assert (
        client.post(
            "/orders",
            json=payload,
        ).status_code
        == 400
    )


def test_non_finite_authoritative_menu_price_fails_closed(monkeypatch):
    menu_item = menu_main.MENUS["test"]["items"][2]
    monkeypatch.setitem(menu_item, "base_price", float("nan"))
    payload = valid_order()
    payload["items"] = [{
        "item_id": "item-003",
        "title": "Masala Dosa",
        "quantity": 1,
        "base_price": 100.0,
        "variation": None,
    }]

    response = client.post(
        "/orders",
        json=payload,
        headers={"Idempotency-Key": "nan-menu-price-test-001"},
    )

    assert response.status_code == 409
    assert "invalid pricing" in response.json()["detail"].lower()
    assert repository.orders == {}


def test_invalid_variation():
    payload = valid_order()

    payload["items"][0]["variation"] = {
        "id": "medium",
        "name": "Medium",
        "price": "250",
    }

    assert (
        client.post(
            "/orders",
            json=payload,
        ).status_code
        == 400
    )


def test_missing_variation_for_item_with_variations():
    payload = valid_order()
    payload["items"][0]["variation"] = None

    assert (
        client.post(
            "/orders",
            json=payload,
        ).status_code
        == 400
    )


def test_empty_order():
    payload = valid_order()
    payload["items"] = []

    assert (
        client.post(
            "/orders",
            json=payload,
        ).status_code
        == 422
    )


def test_order_lookup_and_missing_order_lookup():
    created_response = client.post(
        "/orders",
        json=valid_order(),
    )

    assert created_response.status_code == 201
    created = created_response.json()

    assert client.get(
        f"/orders/{created['order_id']}",
        params={"subdomain": "test", "user_id": "synthetic-user-001"},
    ).json() == created
    assert client.get(
        "/orders/ORD-MISSING",
        params={"subdomain": "test", "user_id": "synthetic-user-001"},
    ).status_code == 404


def test_idempotency_replays_same_order_and_conflicts_on_changed_payload():
    key = "stable-checkout-intent-001"
    first = client.post("/orders", json=valid_order(), headers={"Idempotency-Key": key})
    retry = client.post("/orders", json=valid_order(), headers={"Idempotency-Key": key})

    assert first.status_code == retry.status_code == 201
    assert retry.json() == first.json()
    assert len(repository.orders) == 1

    changed = valid_order()
    changed["items"][0]["quantity"] += 1
    conflict = client.post("/orders", json=changed, headers={"Idempotency-Key": key})
    assert conflict.status_code == 409
    assert len(repository.orders) == 1


def test_idempotency_scope_isolated_by_user_and_order_ownership():
    key = "user-scoped-checkout-01"
    owner = client.post("/orders", json=valid_order(), headers={"Idempotency-Key": key})
    other_payload = valid_order()
    other_payload["user_id"] = "synthetic-user-002"
    other = client.post("/orders", json=other_payload, headers={"Idempotency-Key": key})

    assert owner.status_code == other.status_code == 201
    assert owner.json()["order_id"] != other.json()["order_id"]
    assert client.get(
        f"/orders/{owner.json()['order_id']}",
        params={"subdomain": "test", "user_id": "synthetic-user-002"},
    ).status_code == 404

def test_successful_cancellation_and_lookup_remains_available():
    created_response = client.post(
        "/orders",
        json=valid_order(),
    )

    assert created_response.status_code == 201

    created = created_response.json()

    cancelled = client.delete(
        f"/orders/{created['order_id']}",
        params={"subdomain": "test", "user_id": "synthetic-user-001"},
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    assert (
        client.get(
            f"/orders/{created['order_id']}",
            params={"subdomain": "test", "user_id": "synthetic-user-001"},
        ).json()["status"]
        == "cancelled"
    )


def test_cancel_missing_or_already_cancelled_order():
    assert (
        client.delete(
            "/orders/ORD-MISSING",
            params={"subdomain": "test", "user_id": "synthetic-user-001"},
        ).status_code
        == 404
    )

    created_response = client.post(
        "/orders",
        json=valid_order(),
    )

    assert created_response.status_code == 201

    created = created_response.json()

    assert (
        client.delete(
            f"/orders/{created['order_id']}",
            params={"subdomain": "test", "user_id": "synthetic-user-001"},
        ).status_code
        == 200
    )

    assert (
        client.delete(
            f"/orders/{created['order_id']}",
            params={"subdomain": "test", "user_id": "synthetic-user-001"},
        ).status_code
        == 200
    )


def test_order_lookup_and_cancellation_reject_wrong_tenant_before_mutation():
    try:
        created_response = client.post(
            "/orders", json=valid_order(),
            headers={"Idempotency-Key": "tenant-check-key-01"},
        )
        assert created_response.status_code == 201
        order_id = created_response.json()["order_id"]

        assert client.get(
            f"/orders/{order_id}",
            params={"subdomain": "another-tenant", "user_id": "synthetic-user-001"},
        ).status_code == 404

        rejected_cancel = client.delete(
            f"/orders/{order_id}",
            params={"subdomain": "another-tenant", "user_id": "synthetic-user-001"},
        )
        assert rejected_cancel.status_code == 404

        still_confirmed = client.get(
            f"/orders/{order_id}",
            params={"subdomain": "test", "user_id": "synthetic-user-001"},
        )
        assert still_confirmed.status_code == 200
        assert still_confirmed.json()["status"] == "confirmed"
    finally:
        repository.orders.clear()
        repository.keys.clear()
