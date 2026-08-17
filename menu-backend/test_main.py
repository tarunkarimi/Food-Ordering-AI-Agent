from fastapi.testclient import TestClient

from main import ORDERS, app


client = TestClient(app)


def valid_order():
    return {
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        "items": [{
            "item_id": "item-001", "title": "Chicken Biryani", "quantity": 2,
            "base_price": 220.0, "variation": None,
        }],
    }


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_valid_menu_request():
    response = client.get("/", params={"subdomain": "test"})
    assert response.status_code == 200
    assert response.json()["restaurant_name"] == "Test Restaurant"


def test_valid_order_creation_and_total_calculation():
    response = client.post("/orders", json=valid_order())
    assert response.status_code == 201
    body = response.json()
    assert body["order_id"].startswith("ORD-")
    assert body["subtotal"] == 440.0
    assert body["status"] == "confirmed"


def test_invalid_restaurant():
    payload = valid_order()
    payload["restaurant_name"] = "Wrong Restaurant"
    assert client.post("/orders", json=payload).status_code == 400


def test_invalid_item():
    payload = valid_order()
    payload["items"][0]["item_id"] = "item-999"
    assert client.post("/orders", json=payload).status_code == 400


def test_invalid_quantity():
    payload = valid_order()
    payload["items"][0]["quantity"] = 0
    assert client.post("/orders", json=payload).status_code == 422


def test_invalid_price():
    payload = valid_order()
    payload["items"][0]["base_price"] = 1.0
    assert client.post("/orders", json=payload).status_code == 400


def test_empty_order():
    payload = valid_order()
    payload["items"] = []
    assert client.post("/orders", json=payload).status_code == 422


def test_order_lookup_and_missing_order_lookup():
    ORDERS.clear()
    created = client.post("/orders", json=valid_order()).json()
    assert client.get(f"/orders/{created['order_id']}").json() == created
    assert client.get("/orders/ORD-MISSING").status_code == 404
