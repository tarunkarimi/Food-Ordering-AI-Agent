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
