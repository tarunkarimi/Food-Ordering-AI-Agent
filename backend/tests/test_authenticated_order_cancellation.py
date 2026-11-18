from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from types import SimpleNamespace

from src.api.dependencies import get_current_session
from src.main import app


client = TestClient(app)


def _authenticated_session():
    return Mock(
        user=Mock(id=123),
    )


def _auth_headers():
    return {"Authorization": "Bearer test-access-token"}


def _owned_order(order_id="order-123"):
    return SimpleNamespace(
        order_id=order_id,
        restaurant_name="Test Restaurant",
        subdomain="test",
    )


def _pending_operation():
    return SimpleNamespace(status="pending", id=1, attempts=1)


def test_authenticated_order_cancellation_succeeds():
    app.dependency_overrides[get_current_session] = (
        _authenticated_session
    )

    try:
        with (
            patch("src.api.routes.cart.get_order_history", return_value=_owned_order()),
            patch("src.api.routes.cart.update_order_history_status"),
            patch("src.api.routes.cart.begin_operation", return_value=_pending_operation()),
            patch("src.api.routes.cart.mark_upstream_confirmed"),
            patch("src.api.routes.cart.mark_operation_complete"),
            patch("src.api.routes.cart.requests.delete") as mock_delete,
        ):
            response = Mock()
            response.status_code = 200
            response.json.return_value = {
                "order_id": "order-123",
                "restaurant_name": "Test Restaurant",
                "subdomain": "test",
                "status": "cancelled",
            }
            response.raise_for_status.return_value = None
            mock_delete.return_value = response

            result = client.delete(
                "/api/cart/orders/order-123",
                headers=_auth_headers(),
            )

        assert result.status_code == 200
        assert result.json() == {
            "success": True,
            "order_id": "order-123",
            "status": "cancelled",
        }

        mock_delete.assert_called_once()
        assert mock_delete.call_args.kwargs["params"] == {"subdomain": "test", "user_id": "123"}

    finally:
        app.dependency_overrides.clear()


def test_cancellation_of_another_users_order_fails_before_upstream_call():
    app.dependency_overrides[get_current_session] = _authenticated_session

    try:
        with (
            patch("src.api.routes.cart.get_order_history", return_value=None),
            patch("src.api.routes.cart.requests.delete") as mock_delete,
        ):
            result = client.delete(
                "/api/cart/orders/foreign-order",
                headers=_auth_headers(),
            )

        assert result.status_code == 404
        assert result.json()["detail"] == "Order was not found."
        mock_delete.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_authenticated_order_cancellation_not_found():
    app.dependency_overrides[get_current_session] = (
        _authenticated_session
    )

    try:
        with (
            patch("src.api.routes.cart.get_order_history", return_value=_owned_order("missing-order")),
            patch("src.api.routes.cart.begin_operation", return_value=_pending_operation()),
            patch("src.api.routes.cart.requests.delete") as mock_delete,
        ):
            response = Mock()
            response.status_code = 404
            mock_delete.return_value = response

            result = client.delete(
                "/api/cart/orders/missing-order",
                headers=_auth_headers(),
            )

        assert result.status_code == 404
        assert result.json()["detail"] == (
            "Order missing-order was not found."
        )

    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "identity_fields",
    [
        {"restaurant_name": "Other Restaurant", "subdomain": "test"},
        {"restaurant_name": "Test Restaurant", "subdomain": "other"},
        {"restaurant_name": "Test Restaurant", "subdomain": ""},
        {"restaurant_name": "Test Restaurant"},
    ],
)
def test_cancellation_rejects_invalid_upstream_identity_without_updating_history(identity_fields):
    app.dependency_overrides[get_current_session] = _authenticated_session

    try:
        with (
            patch("src.api.routes.cart.get_order_history", return_value=_owned_order()),
            patch("src.api.routes.cart.update_order_history_status") as update_status,
            patch("src.api.routes.cart.begin_operation", return_value=_pending_operation()),
            patch("src.api.routes.cart.mark_upstream_confirmed"),
            patch("src.api.routes.cart.requests.delete") as mock_delete,
        ):
            response = Mock()
            response.status_code = 200
            response.json.return_value = {
                "order_id": "order-123",
                **identity_fields,
                "status": "cancelled",
            }
            response.raise_for_status.return_value = None
            mock_delete.return_value = response

            result = client.delete(
                "/api/cart/orders/order-123",
                headers=_auth_headers(),
            )

        assert result.status_code == 502
        assert "invalid response" in result.json()["detail"]
        update_status.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_order_cancellation_requires_authentication():
    result = client.delete(
        "/api/cart/orders/order-123",
    )

    assert result.status_code in {401, 403}


def test_authenticated_order_cancellation_service_failure():
    app.dependency_overrides[get_current_session] = (
        _authenticated_session
    )

    try:
        import requests

        with (
            patch("src.api.routes.cart.get_order_history", return_value=_owned_order()),
            patch("src.api.routes.cart.begin_operation", return_value=_pending_operation()),
            patch("src.api.routes.cart.mark_operation_retryable"),
            patch("src.api.routes.cart.requests.delete") as mock_delete,
        ):
            mock_delete.side_effect = (
                requests.ConnectionError()
            )

            result = client.delete(
                "/api/cart/orders/order-123",
                headers=_auth_headers(),
            )

        assert result.status_code == 503
        assert result.json()["detail"] == (
            "Unable to cancel order: the ordering "
            "service is unavailable."
        )

    finally:
        app.dependency_overrides.clear()
from datetime import datetime, timezone

from src.db.database import SessionLocal
from src.db.models import OrderHistory, User

from tests.test_authenticated_cart import (
    auth_headers,
    signup_and_login,
)


def test_cancellation_updates_persistent_order_history():
    user_id, token = signup_and_login()

    try:
        order_id = f"history-cancel-{datetime.now(timezone.utc).timestamp()}"

        with SessionLocal() as db:
            db.add(
                OrderHistory(
                    user_id=user_id,
                    order_id=order_id,
                    restaurant_name="Test Restaurant",
                    subdomain="test",
                    status="confirmed",
                    subtotal=220.0,
                    total_items=1,
                    items_json=(
                        '[{"item_id":"item-001",'
                        '"title":"Chicken Biryani",'
                        '"quantity":1,'
                        '"base_price":220.0,'
                        '"variation":null}]'
                    ),
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            db.commit()

        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src.main import app

        client = TestClient(app)

        with patch("src.api.routes.cart.requests.delete") as mock_delete:
            mock_delete.return_value.status_code = 200
            mock_delete.return_value.json.return_value = {
                "order_id": order_id,
                "restaurant_name": "Test Restaurant",
                "subdomain": "test",
                "status": "cancelled",
            }
            mock_delete.return_value.raise_for_status.return_value = None

            response = client.delete(
                f"/api/cart/orders/{order_id}",
                headers=auth_headers(token),
            )

        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"

        with SessionLocal() as db:
            history = db.query(OrderHistory).filter(
                OrderHistory.order_id == order_id,
                OrderHistory.user_id == user_id,
            ).one()

            assert history.status == "cancelled"
    finally:
        with SessionLocal() as db:
            db.execute(delete(User).where(User.id == user_id))
            db.commit()


def test_cancellation_retry_reconciles_local_history_without_second_delete():
    user_id, token = signup_and_login()
    order_id = f"history-cancel-reconcile-{datetime.now(timezone.utc).timestamp()}"

    try:
        with SessionLocal() as db:
            db.add(OrderHistory(
                user_id=user_id,
                order_id=order_id,
                restaurant_name="Test Restaurant",
                subdomain="test",
                status="confirmed",
                subtotal=220.0,
                total_items=1,
                items_json='[{"item_id":"item-001","title":"Synthetic item","quantity":1,"base_price":220.0,"variation":null}]',
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ))
            db.commit()

        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src.api.routes import cart as cart_route
        from src.main import app

        client = TestClient(app)
        original_update = cart_route.update_order_history_status
        update_attempts = 0

        def fail_once_then_update(db, *, user_id, order_id, status):
            nonlocal update_attempts
            update_attempts += 1
            if update_attempts == 1:
                raise RuntimeError("synthetic local persistence failure")
            return original_update(
                db,
                user_id=user_id,
                order_id=order_id,
                status=status,
            )

        response_body = {
            "order_id": order_id,
            "restaurant_name": "Test Restaurant",
            "subdomain": "test",
            "status": "cancelled",
        }
        with (
            patch.object(
                cart_route,
                "update_order_history_status",
                side_effect=fail_once_then_update,
            ),
            patch("src.api.routes.cart.requests.delete") as mock_delete,
        ):
            mock_delete.return_value.status_code = 200
            mock_delete.return_value.json.return_value = response_body
            mock_delete.return_value.raise_for_status.return_value = None

            first = client.delete(f"/api/cart/orders/{order_id}", headers=auth_headers(token))
            retry = client.delete(f"/api/cart/orders/{order_id}", headers=auth_headers(token))

        assert first.status_code == 503
        assert retry.status_code == 200
        assert retry.json()["status"] == "cancelled"
        mock_delete.assert_called_once()
        with SessionLocal() as db:
            history = db.query(OrderHistory).filter(
                OrderHistory.order_id == order_id,
                OrderHistory.user_id == user_id,
            ).one()
            assert history.status == "cancelled"
    finally:
        with SessionLocal() as db:
            db.execute(delete(User).where(User.id == user_id))
            db.commit()
