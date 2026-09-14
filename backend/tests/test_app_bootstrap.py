"""Application bootstrap regression tests."""

from src.main import app, create_app


def test_create_app_returns_fastapi_application():
    created_app = create_app()

    assert created_app.title == "Food Ordering AI Agent"
    assert created_app.version == "1.0.0"


def test_application_registers_core_routes():
    paths = set(app.openapi()["paths"])

    assert "/" in paths
    assert "/health" in paths
    assert "/ready" in paths

    assert "/api/auth/login" in paths
    assert "/api/cart" in paths

    order_paths = {
        path
        for path in paths
        if path.startswith("/api/orders")
    }
    assert order_paths

    preference_paths = {
        path
        for path in paths
        if path.startswith("/api/preferences")
    }
    assert preference_paths

    chat_paths = {
        path
        for path in paths
        if path.startswith("/api/chats")
    }
    assert chat_paths
