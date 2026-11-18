"""PostgreSQL-only order persistence, ownership, and idempotency regressions.

This module is registered only in the isolated PostgreSQL CI job. Do not run
it against a local or application database.
"""

from concurrent.futures import ThreadPoolExecutor
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.engine import make_url

from order_storage import (
    IdempotencyConflict,
    MenuOrder,
    PostgresOrderRepository,
    request_fingerprint,
)


@pytest.fixture
def order_context():
    if os.getenv("CI", "").casefold() != "true":
        pytest.fail("PostgreSQL order integration tests are CI-only.")
    expected_name = os.getenv("MENU_TEST_DATABASE_NAME", "")
    if (
        not expected_name
        or os.getenv("MENU_TEST_DATABASE_CONFIRMATION")
        != f"I_ACKNOWLEDGE_TEST_DATABASE:{expected_name}"
        or not any(segment in expected_name.casefold().replace("-", "_").split("_") for segment in ("test", "ci", "e2e"))
    ):
        pytest.fail("A matching explicit menu test-database designation is required.")
    target = os.getenv("MENU_DATABASE_URL", "")
    try:
        parsed = make_url(target)
    except Exception as exc:
        pytest.fail("A valid explicitly designated menu test database is required.")
    if (
        parsed.get_backend_name() not in {"postgres", "postgresql"}
        or not parsed.host
        or parsed.database != expected_name
    ):
        pytest.fail("Menu integration tests may only use the designated CI PostgreSQL database.")
    user_id = f"phase21-{uuid4().hex}"
    repository = PostgresOrderRepository()
    yield repository, user_id
    with repository.sessions() as session, session.begin():
        session.execute(delete(MenuOrder).where(MenuOrder.user_id == user_id))
    repository.engine.dispose()


def payload(user_id: str, *, quantity: int = 2, subdomain: str = "test"):
    request = {
        "user_id": user_id,
        "subdomain": subdomain,
        "restaurant_name": "Test Restaurant",
        "items": [{
            "item_id": "synthetic-item-1",
            "title": "Synthetic Item",
            "quantity": quantity,
            "base_price": 12.5,
            "variation": None,
        }],
        "subtotal": quantity * 12.5,
    }
    return {
        **request,
        "idempotency_key": "phase21-key-" + user_id[-12:],
        "request_fingerprint": request_fingerprint(request),
    }


def test_order_survives_fresh_repository_and_cancel_is_durable(order_context):
    first, user_id = order_context
    created, replayed = first.create_order(payload(user_id))
    assert replayed is False

    second = PostgresOrderRepository()
    assert second.get_order(
        created["order_id"], user_id=user_id, subdomain="test"
    ) == created

    cancelled = second.cancel_order(
        created["order_id"], user_id=user_id, subdomain="test"
    )
    assert cancelled["status"] == "cancelled"
    assert second.cancel_order(
        created["order_id"], user_id=user_id, subdomain="test"
    )["status"] == "cancelled"
    assert first.get_order(
        created["order_id"], user_id=user_id, subdomain="test"
    )["status"] == "cancelled"
    second.engine.dispose()


def test_idempotency_replay_conflict_user_and_tenant_isolation(order_context):
    repository, user_id = order_context
    original = payload(user_id)
    created, _ = repository.create_order(original)

    replay = repository.get_idempotent_order(
        user_id=user_id,
        subdomain="test",
        idempotency_key=original["idempotency_key"],
        fingerprint=original["request_fingerprint"],
    )
    assert replay == created

    changed = payload(user_id, quantity=3)
    changed["idempotency_key"] = original["idempotency_key"]
    with pytest.raises(IdempotencyConflict):
        repository.get_idempotent_order(
            user_id=user_id,
            subdomain="test",
            idempotency_key=changed["idempotency_key"],
            fingerprint=changed["request_fingerprint"],
        )

    assert repository.get_order(
        created["order_id"], user_id="another-user", subdomain="test"
    ) is None
    assert repository.get_order(
        created["order_id"], user_id=user_id, subdomain="other-tenant"
    ) is None
    assert repository.get_idempotent_order(
        user_id="another-user",
        subdomain="test",
        idempotency_key=original["idempotency_key"],
        fingerprint=original["request_fingerprint"],
    ) is None

    other_tenant_payload = payload(user_id, subdomain="other-tenant")
    other_tenant_payload["idempotency_key"] = original["idempotency_key"]
    other_tenant_order, replayed = repository.create_order(other_tenant_payload)
    assert replayed is False
    assert other_tenant_order["order_id"] != created["order_id"]
    assert repository.get_idempotent_order(
        user_id=user_id,
        subdomain="other-tenant",
        idempotency_key=original["idempotency_key"],
        fingerprint=other_tenant_payload["request_fingerprint"],
    ) == other_tenant_order


def test_concurrent_same_key_creates_exactly_one_order(order_context):
    repository, user_id = order_context
    order = payload(user_id)

    def create():
        repository = PostgresOrderRepository()
        try:
            return repository.create_order(order)
        finally:
            repository.engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))

    assert results[0][0]["order_id"] == results[1][0]["order_id"]
    assert sorted(result[1] for result in results) == [False, True]
    repository.engine.dispose()


def test_concurrent_cancellation_preserves_cancelled_state(order_context):
    repository, user_id = order_context
    created, _ = repository.create_order(payload(user_id))

    def cancel():
        instance = PostgresOrderRepository()
        try:
            return instance.cancel_order(
                created["order_id"], user_id=user_id, subdomain="test"
            )
        finally:
            instance.engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: cancel(), range(2)))

    assert [result["status"] for result in results] == ["cancelled", "cancelled"]
    assert repository.get_order(
        created["order_id"], user_id=user_id, subdomain="test"
    )["status"] == "cancelled"
