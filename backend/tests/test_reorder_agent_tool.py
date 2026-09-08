from src.agents.tools.reorder import reorder_previous_order


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
