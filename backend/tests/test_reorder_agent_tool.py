from src.agents.tools.reorder import reorder_previous_order


from src.agents.tools import cart as cart_tools
from src.agents.tools import reorder as reorder_tool
import pytest


class _SessionContext:
    def __enter__(self):
        return object()

    def __exit__(self, *args):
        return False


class _MenuResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _chat_state(tenant="tenant-a"):
    return {
        "user_id": 41,
        "restaurant_name": "Shared Kitchen",
        "subdomain": tenant,
    }


def _historical_order(subdomain="tenant-a"):
    return {
        "order_id": "synthetic-order",
        "restaurant_name": "Shared Kitchen",
        "subdomain": subdomain,
        "status": "confirmed",
        "items": [{
            "item_id": "shared-item",
            "title": "Same Dish",
            "quantity": 2,
            "variation": None,
        }],
    }


def _invoke(state):
    return reorder_previous_order.invoke({
        "name": "reorder_previous_order",
        "args": {"state": state, "order_id": "synthetic-order"},
        "type": "tool_call",
        "id": "synthetic-reorder-call",
    })


def test_reorder_requires_authenticated_user():
    result = reorder_previous_order.invoke(
        {
            "name": "reorder_previous_order",
            "args": {
                "state": {
                    "user_id": None,
                    "restaurant_name": "Test Restaurant",
                    "subdomain": "test",
                }
            },
            "type": "tool_call",
            "id": "test-call",
        }
    )

    assert "signed in" in str(result).lower()


def test_reorder_tool_is_exposed():
    assert reorder_previous_order.name == "reorder_previous_order"


def test_reorder_tool_mentions_current_pricing():
    description = reorder_previous_order.description.lower()

    assert "current menu" in description
    assert "prices" in description


def test_reorder_tool_does_not_claim_checkout():
    description = reorder_previous_order.description.lower()

    assert "does not place" in description
    assert "confirm" in description


def test_same_tenant_reorder_uses_historical_identity_and_current_menu_price(monkeypatch):
    requested_urls = []
    cart_writes = []
    menu = {
        "restaurant_name": "Shared Kitchen",
        "subdomain": "tenant-a",
        "items": [{
            "id": "shared-item",
            "title": "Same Dish",
            "base_price": 175,
            "variations": [],
        }],
    }
    monkeypatch.setattr(reorder_tool, "SessionLocal", _SessionContext)
    monkeypatch.setattr(
        reorder_tool,
        "get_reorder_items",
        lambda db, *, user_id, order_id: _historical_order(),
    )
    monkeypatch.setattr(
        cart_tools,
        "request_read_with_retry",
        lambda request: request(),
    )
    monkeypatch.setattr(
        cart_tools.requests,
        "get",
        lambda url, timeout: requested_urls.append(url) or _MenuResponse(menu),
    )
    monkeypatch.setattr(
        reorder_tool,
        "add_reorder_items_to_cart",
        lambda db, *, user_id, restaurant_name, subdomain, items:
        cart_writes.append({
            "user_id": user_id,
            "restaurant_name": restaurant_name,
            "subdomain": subdomain,
            "items": items,
        }),
    )
    monkeypatch.setattr(
        reorder_tool,
        "load_langgraph_cart",
        lambda db, **kwargs: {"items": []},
    )

    result = _invoke(_chat_state("tenant-a"))

    assert "today's menu and prices" in result.update["messages"][0].content
    assert "?subdomain=tenant-a" in requested_urls[0]
    assert cart_writes[0]["subdomain"] == "tenant-a"
    assert cart_writes[0]["restaurant_name"] == "Shared Kitchen"
    assert cart_writes[0]["items"][0]["unit_price"] == 175


@pytest.mark.parametrize(
    "historical_subdomain",
    [None, "", "   ", 17],
    ids=["missing", "blank", "whitespace", "malformed"],
)
def test_unverified_order_fails_before_menu_or_cart_write(
    monkeypatch, historical_subdomain,
):
    requested_urls = []
    cart_writes = []
    historical = _historical_order(subdomain=historical_subdomain)
    monkeypatch.setattr(reorder_tool, "SessionLocal", _SessionContext)
    monkeypatch.setattr(
        reorder_tool,
        "get_reorder_items",
        lambda db, *, user_id, order_id: historical,
    )
    monkeypatch.setattr(
        cart_tools.requests,
        "get",
        lambda url, timeout: requested_urls.append(url)
        or pytest.fail("menu must not be fetched for an unverified order"),
    )
    monkeypatch.setattr(
        reorder_tool,
        "add_reorder_items_to_cart",
        lambda db, **kwargs: cart_writes.append(kwargs),
    )

    result = _invoke(_chat_state("tenant-a"))

    message = result.update["messages"][0].content
    assert "cart was not changed" in message.lower()
    assert requested_urls == []
    assert cart_writes == []


def test_cross_tenant_order_with_duplicate_item_identity_is_rejected(monkeypatch):
    cart_writes = []
    requested_urls = []
    historical = _historical_order(subdomain="tenant-a")
    tenant_b_menu = {
        "restaurant_name": "Shared Kitchen",
        "subdomain": "tenant-b",
        "items": [{
            "id": "shared-item",
            "title": "Same Dish",
            "base_price": 175,
            "variations": [],
        }],
    }
    monkeypatch.setattr(reorder_tool, "SessionLocal", _SessionContext)
    monkeypatch.setattr(
        reorder_tool,
        "get_reorder_items",
        lambda db, *, user_id, order_id: historical,
    )
    monkeypatch.setattr(
        cart_tools.requests,
        "get",
        lambda url, timeout: requested_urls.append(url)
        or _MenuResponse(tenant_b_menu),
    )
    monkeypatch.setattr(
        cart_tools,
        "request_read_with_retry",
        lambda request: request(),
    )
    monkeypatch.setattr(
        reorder_tool,
        "add_reorder_items_to_cart",
        lambda db, *, user_id, restaurant_name, subdomain, items:
        cart_writes.append(items),
    )
    monkeypatch.setattr(
        reorder_tool,
        "load_langgraph_cart",
        lambda db, **kwargs: {"items": []},
    )

    result = _invoke(_chat_state("tenant-b"))

    assert "different restaurant" in result.update["messages"][0].content.lower()
    assert requested_urls == []
    assert cart_writes == []
