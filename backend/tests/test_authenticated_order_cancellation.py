from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from src.api.dependencies import get_current_session
from src.main import app


client = TestClient(app)


def _authenticated_session():
    return Mock(
        user=Mock(id=123),
    )


def _auth_headers():
    return {"Authorization": "Bearer test-access-token"}


def test_authenticated_order_cancellation_succeeds():
    app.dependency_overrides[get_current_session] = (
        _authenticated_session
    )

    try:
        with patch(
            "src.api.routes.cart.requests.delete"
        ) as mock_delete:
            response = Mock()
            response.status_code = 200
            response.json.return_value = {
                "order_id": "order-123",
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

    finally:
        app.dependency_overrides.clear()


def test_authenticated_order_cancellation_not_found():
    app.dependency_overrides[get_current_session] = (
        _authenticated_session
    )

    try:
        with patch(
            "src.api.routes.cart.requests.delete"
        ) as mock_delete:
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

        with patch(
            "src.api.routes.cart.requests.delete"
        ) as mock_delete:
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
from src.db.models import OrderHistory

from tests.test_authenticated_cart import (
    auth_headers,
    signup_and_login,
)


def test_cancellation_updates_persistent_order_history():
    user_id, token = signup_and_login()

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
