"""Authentication helpers for server-to-server menu/order requests."""

from src.configs.config import config


def menu_service_headers() -> dict[str, str]:
    """Return the private service credential without logging its value."""
    return {"X-Menu-Service-Key": config.MENU_SERVICE_API_KEY}
