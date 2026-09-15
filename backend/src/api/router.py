"""Application router registration."""

from fastapi import APIRouter

from src.api.routes.auth import router as auth_router
from src.api.routes.cart import router as cart_router
from src.api.routes.chats import router as chat_router
from src.api.routes.orders import router as orders_router
from src.api.routes.ordering_intelligence import (
    router as ordering_intelligence_router,
)
from src.api.routes.preferences import router as preferences_router
from src.api.routes.reorder import router as reorder_router

api_router = APIRouter()

api_router.include_router(
    auth_router,
    prefix="/api/auth",
    tags=["authentication"],
)

api_router.include_router(
    cart_router,
    prefix="/api/cart",
    tags=["cart"],
)

api_router.include_router(
    orders_router,
    prefix="/api/orders",
    tags=["orders"],
)

api_router.include_router(
    reorder_router,
    prefix="/api/orders",
    tags=["orders"],
)

api_router.include_router(
    ordering_intelligence_router,
    prefix="/api/ordering-intelligence",
    tags=["ordering-intelligence"],
)

api_router.include_router(
    preferences_router,
    prefix="/api/preferences",
    tags=["preferences"],
)

api_router.include_router(
    chat_router,
    prefix="/api/chats",
    tags=["workflows"],
)
