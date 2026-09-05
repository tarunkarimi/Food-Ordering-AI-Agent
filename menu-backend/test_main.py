from fastapi.testclient import TestClient

from main import ORDERS, app


client = TestClient(app)


def valid_order():
    return {
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
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
    ORDERS.clear()

    created_response = client.post(
        "/orders",
        json=valid_order(),
    )

    assert created_response.status_code == 201

    created = created_response.json()

    assert (
        client.get(
            f"/orders/{created['order_id']}"
        ).json()
        == created
    )

    assert (
        client.get(
            "/orders/ORD-MISSING"
        ).status_code
        == 404
    )


def test_successful_cancellation_and_lookup_remains_available():
    ORDERS.clear()

    created_response = client.post(
        "/orders",
        json=valid_order(),
    )

    assert created_response.status_code == 201

    created = created_response.json()

    cancelled = client.delete(
        f"/orders/{created['order_id']}"
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    assert (
        client.get(
            f"/orders/{created['order_id']}"
        ).json()["status"]
        == "cancelled"
    )


def test_cancel_missing_or_already_cancelled_order():
    assert (
        client.delete(
            "/orders/ORD-MISSING"
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
            f"/orders/{created['order_id']}"
        ).status_code
        == 200
    )

    assert (
        client.delete(
            f"/orders/{created['order_id']}"
        ).status_code
        == 400
    )