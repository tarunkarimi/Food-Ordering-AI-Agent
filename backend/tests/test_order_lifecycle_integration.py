"""End-to-end order lifecycle through the production LangGraph tool wiring.

The synthetic AI tool calls are the only model substitute. Every order request
uses a real HTTP connection to a temporary instance of the menu backend.
"""

import importlib.util
import os
import socket
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
import uvicorn
from sqlalchemy.engine import make_url
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from src.agents.nodes.tool_node import tool_node
from src.agents.state import Cart, OrderState
from src.configs.config import config
from src.db.database import SessionLocal
from src.db.models import User
from sqlalchemy import delete


def _load_menu_backend():
    main_path = (
        Path(__file__).resolve().parents[2]
        / "menu-backend"
        / "main.py"
    )
    menu_directory = str(main_path.parent)
    if menu_directory not in sys.path:
        sys.path.insert(0, menu_directory)

    spec = importlib.util.spec_from_file_location(
        "integration_menu_backend",
        main_path,
    )

    module = importlib.util.module_from_spec(spec)

    assert spec.loader is not None

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return module


def _available_port():
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def menu_backend(monkeypatch):
    if os.getenv("CI", "").casefold() != "true":
        pytest.fail("Order lifecycle persistence integration is CI-only.")
    menu_url = os.getenv("MENU_DATABASE_URL", "")
    test_url = os.getenv("TEST_DATABASE_URL", "")
    menu_test_name = os.getenv("MENU_TEST_DATABASE_NAME", "")
    if (
        not menu_test_name
        or menu_test_name != os.getenv("TEST_DATABASE_NAME")
        or os.getenv("MENU_TEST_DATABASE_CONFIRMATION")
        != f"I_ACKNOWLEDGE_TEST_DATABASE:{menu_test_name}"
    ):
        pytest.fail("The menu integration database requires its own matching CI test designation.")
    try:
        menu_target = make_url(menu_url)
        test_target = make_url(test_url)
    except Exception:
        pytest.fail("The menu integration database must match the designated CI database.")
    if (
        not menu_target.host
        or menu_target.get_backend_name() not in {"postgres", "postgresql"}
        or (menu_target.host, menu_target.port or 5432, menu_target.database)
        != (test_target.host, test_target.port or 5432, test_target.database)
        or test_target.database != os.getenv("TEST_DATABASE_NAME")
        or os.getenv("TEST_DATABASE_CONFIRMATION")
        != f"I_ACKNOWLEDGE_TEST_DATABASE:{os.getenv('TEST_DATABASE_NAME', '')}"
    ):
        pytest.fail("The menu integration database must match the designated CI test database.")
    menu = _load_menu_backend()

    port = _available_port()

    server = uvicorn.Server(
        uvicorn.Config(
            menu.app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )

    thread = threading.Thread(
        target=server.run,
        daemon=True,
    )

    thread.start()

    base_url = f"http://127.0.0.1:{port}"

    for _ in range(50):
        try:
            if (
                requests.get(
                    f"{base_url}/health",
                    timeout=0.1,
                ).status_code
                == 200
            ):
                break
        except requests.ConnectionError:
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=2)
        pytest.fail(
            "Menu backend did not start"
        )

    monkeypatch.setattr(
        config,
        "MENU_BACKEND_URL",
        base_url,
    )

    yield SimpleNamespace(url=base_url, module=menu)

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def synthetic_order_user(menu_backend):
    from tests.test_authenticated_cart import signup_and_login

    user_id, _token = signup_and_login()
    yield user_id

    repository = menu_backend.module.get_order_repository()
    import order_storage
    with repository.sessions() as session, session.begin():
        session.execute(delete(order_storage.MenuOrder).where(
            order_storage.MenuOrder.user_id == str(user_id)
        ))
    repository.engine.dispose()
    with SessionLocal() as db:
        db.execute(delete(User).where(User.id == user_id))
        db.commit()


@pytest.fixture
def tool_graph():
    graph = StateGraph(OrderState)

    graph.add_node("tools", tool_node)
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)

    return graph.compile()


def invoke_tool(
    graph,
    state,
    name,
    args,
    tool_call_id,
):
    state = dict(state)

    state["messages"] = list(
        state.get("messages", [])
    ) + [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "args": args,
                    "id": tool_call_id,
                    "type": "tool_call",
                }
            ],
        )
    ]

    return graph.invoke(state)


def initial_state(user_id):
    return {
        "messages": [],
        "cart": Cart(items=[]),
        "orderId": None,
        "order_status": None,
        "order_confirmation_pending": False,
        "restaurant_name": "Test Restaurant",
        "subdomain": "test",
        # Tools require the authenticated graph owner before they inspect or
        # call the order backend. This synthetic identity is isolated to this
        # in-process integration test.
        "user_id": user_id,
        "finished": False,
    }


def test_order_lifecycle_over_real_menu_backend(
    menu_backend,
    tool_graph,
    synthetic_order_user,
):
    state = initial_state(synthetic_order_user)

    # 1. The agent's registered add_cart tool builds the cart.
    # Chicken Biryani has variations, so the test explicitly selects Regular.
    state = invoke_tool(
        tool_graph,
        state,
        "add_cart",
        {
            "item_id": "item-001",
            "title": "Chicken Biryani",
            "new_item": {
                "key": "item-001|regular",
                "quantity": 2,
                "base_price": 220.0,
                "variation": {
                    "id": "regular",
                    "name": "Regular",
                    "price": "220",
                },
            },
        },
        "add-regular",
    )

    assert len(state["cart"].items) == 1
    assert state["cart"].items[0].units[0].quantity == 2
    assert state["cart"].items[0].units[0].variation is not None
    assert (
        state["cart"].items[0].units[0].variation.id
        == "regular"
    )

    # 2. Explicit customer confirmation is required before placement.
    state["order_confirmation_pending"] = True
    state["messages"] = [
        HumanMessage(content="yes")
    ]

    # 3. place_order sends an actual POST to the running menu backend.
    state = invoke_tool(
        tool_graph,
        state,
        "place_order",
        {},
        "place-order",
    )

    order_id = state["orderId"]

    assert order_id
    assert order_id.startswith("ORD-")
    assert state["order_status"] == "confirmed"
    assert state["cart"].items == []
    assert state["finished"] is True
    assert (
        state["order_confirmation_pending"] is False
    )

    # 4. Status lookup fetches the same persisted order through an actual GET.
    state_before_status = dict(state)

    state = invoke_tool(
        tool_graph,
        state,
        "get_order_status",
        {},
        "confirmed-status",
    )

    assert (
        "is confirmed."
        in state["messages"][-1].content
    )
    assert (
        state["cart"]
        == state_before_status["cart"]
    )
    assert (
        state["orderId"]
        == state_before_status["orderId"]
    )
    assert (
        state["finished"]
        is state_before_status["finished"]
    )

    # 5. Cancellation sends an actual DELETE and changes only lifecycle status.
    state_before_cancel = dict(state)

    state = invoke_tool(
        tool_graph,
        state,
        "cancel_order",
        {},
        "cancel-order",
    )

    assert state["order_status"] == "cancelled"
    assert state["cart"] == state_before_cancel["cart"]
    assert state["orderId"] == order_id
    assert (
        state["finished"]
        is state_before_cancel["finished"]
    )

    # 6. The persisted order remains retrievable and reports cancelled status.
    state = invoke_tool(
        tool_graph,
        state,
        "get_order_status",
        {},
        "cancelled-status",
    )

    assert (
        "Order "
        + order_id
        + " is cancelled."
        in state["messages"][-1].content
    )
    assert (
        "Status: cancelled"
        in state["messages"][-1].content
    )

    # 7. A real backend 404 must not alter the existing lifecycle state.
    before_missing_cancel = dict(state)

    # The unknown-order ownership lookup normally consults persistence before
    # making an upstream request. Keep this in-process integration test
    # database-independent while exercising the real menu backend's 404 path.
    with (
        patch("src.agents.tools.order.SessionLocal"),
        patch(
            "src.agents.tools.order.begin_operation",
            return_value=SimpleNamespace(status="pending", attempts=1, id=1),
        ),
        patch("src.agents.tools.order.mark_operation_retryable"),
        patch(
            "src.agents.tools.order.get_order_history",
            return_value=SimpleNamespace(
                order_id="ORD-MISSING",
                restaurant_name="Test Restaurant",
                subdomain="test",
            ),
        ),
    ):
        state = invoke_tool(
            tool_graph,
            state,
            "cancel_order",
            {
                "order_id": "ORD-MISSING",
            },
            "missing-cancel",
        )

    assert isinstance(
        state["messages"][-1],
        ToolMessage,
    )
    assert (
        "was not found"
        in state["messages"][-1].content
    )
    assert (
        state["cart"]
        == before_missing_cancel["cart"]
    )
    assert (
        state["orderId"]
        == before_missing_cancel["orderId"]
    )
    assert (
        state["order_status"]
        == before_missing_cancel["order_status"]
    )
    assert (
        state["finished"]
        is before_missing_cancel["finished"]
    )


def test_new_order_can_be_placed_after_completed_order(
    menu_backend,
    tool_graph,
    synthetic_order_user,
):
    state = initial_state(synthetic_order_user)

    # First order.
    state = invoke_tool(
        tool_graph,
        state,
        "add_cart",
        {
            "item_id": "item-001",
            "title": "Chicken Biryani",
            "new_item": {
                "key": "item-001|large",
                "quantity": 1,
                "base_price": 280.0,
                "variation": {
                    "id": "large",
                    "name": "Large",
                    "price": "280",
                },
            },
        },
        "first-add",
    )

    state["order_confirmation_pending"] = True
    state["messages"] = [
        HumanMessage(content="yes")
    ]

    state = invoke_tool(
        tool_graph,
        state,
        "place_order",
        {},
        "first-place",
    )

    first_order_id = state["orderId"]

    assert first_order_id
    assert state["finished"] is True
    assert state["cart"].items == []

    # Starting a new cart must reopen the active-order lifecycle.
    state = invoke_tool(
        tool_graph,
        state,
        "add_cart",
        {
            "item_id": "item-003",
            "title": "Masala Dosa",
            "new_item": {
                "key": "item-003|no_variant",
                "quantity": 1,
                "base_price": 100.0,
            },
        },
        "second-add",
    )

    assert state["finished"] is False
    assert len(state["cart"].items) == 1
    assert (
        state["cart"].items[0].item_id
        == "item-003"
    )

    # Confirm and place the second order.
    state["order_confirmation_pending"] = True
    state["messages"] = [
        HumanMessage(content="yes")
    ]

    state = invoke_tool(
        tool_graph,
        state,
        "place_order",
        {},
        "second-place",
    )

    second_order_id = state["orderId"]

    assert second_order_id
    assert second_order_id != first_order_id
    assert state["order_status"] == "confirmed"
    assert state["cart"].items == []
    assert state["finished"] is True
    assert (
        state["order_confirmation_pending"] is False
    )
