import logging
import hmac
import json
from math import isfinite
import os
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from order_storage import (
    IdempotencyConflict,
    OrderRepository,
    OrderStorageUnavailable,
    get_order_repository,
    request_fingerprint,
)


# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


def _log_order_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Write compact structured lifecycle events without keys or user data."""
    logger.log(
        level,
        json.dumps({"event": event, **fields}, separators=(",", ":"), default=str),
    )


# ------------------------------------------------------------------
# Application configuration
# ------------------------------------------------------------------

PORT = int(os.getenv("PORT", "8000"))
MENU_SERVICE_API_KEY = os.getenv("MENU_SERVICE_API_KEY", "")


# ------------------------------------------------------------------
# Application
# ------------------------------------------------------------------

app = FastAPI(
    title="Food Ordering Menu Backend",
    description="Menu and order service for the Food Ordering AI Agent",
    version="1.0.0",
)


# Allow the deployed frontend and local development frontend to call this API.
# Render can override FRONTEND_ORIGINS with a comma-separated list.
FRONTEND_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,https://food-ordering-frontend-odsb.onrender.com",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# Menu data
# ------------------------------------------------------------------

MENUS = {
    "test": {
        "restaurant_name": "Test Restaurant",
        "items": [
            {
                "id": "item-001",
                "title": "Chicken Biryani",
                "description": "Aromatic basmati rice with spicy chicken.",
                "base_price": 220.0,
                "variations": [
                    {
                        "id": "regular",
                        "name": "Regular",
                        "price": "220",
                    },
                    {
                        "id": "large",
                        "name": "Large",
                        "price": "280",
                    },
                ],
            },
            {
                "id": "item-002",
                "title": "Paneer Butter Masala",
                "description": "Paneer cooked in a rich tomato and butter gravy.",
                "base_price": 180.0,
                "variations": [
                    {
                        "id": "regular",
                        "name": "Regular",
                        "price": "180",
                    },
                    {
                        "id": "large",
                        "name": "Large",
                        "price": "230",
                    },
                ],
            },
            {
                "id": "item-003",
                "title": "Masala Dosa",
                "description": "Crispy dosa served with potato masala.",
                "base_price": 100.0,
                "variations": [],
            },
            {
                "id": "item-004",
                "title": "Veg Fried Rice",
                "description": "Indo-Chinese fried rice with fresh vegetables.",
                "base_price": 140.0,
                "variations": [
                    {
                        "id": "regular",
                        "name": "Regular",
                        "price": "140",
                    },
                    {
                        "id": "large",
                        "name": "Large",
                        "price": "190",
                    },
                ],
            },
            {
                "id": "item-005",
                "title": "Chicken 65",
                "description": "Crispy spicy fried chicken.",
                "base_price": 200.0,
                "variations": [],
            },
        ],
    }
}


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class OrderItemRequest(BaseModel):
    item_id: str
    title: str
    quantity: int = Field(gt=0)
    base_price: float
    variation: Optional[Any] = None


class OrderRequest(BaseModel):
    restaurant_name: str
    subdomain: str
    user_id: str = Field(min_length=1, max_length=128)
    items: list[OrderItemRequest] = Field(min_length=1)


def require_menu_service_key(
    x_menu_service_key: str | None = Header(default=None),
) -> None:
    """Protect order operations from direct unauthenticated callers."""
    if len(MENU_SERVICE_API_KEY) < 32:
        raise HTTPException(
            status_code=503,
            detail="Order service authentication is not configured.",
        )
    if not isinstance(x_menu_service_key, str) or not hmac.compare_digest(
        x_menu_service_key,
        MENU_SERVICE_API_KEY,
    ):
        raise HTTPException(
            status_code=401,
            detail="Order service authentication required.",
        )


def _menu_item_is_available(item: dict[str, Any]) -> bool:
    """Fail closed on explicit or malformed availability metadata."""
    for field in ("available", "is_available", "is_active"):
        if field in item and (
            not isinstance(item[field], bool) or item[field] is False
        ):
            return False
    if "status" in item:
        if not isinstance(item["status"], str):
            return False
        if item["status"].strip().casefold() not in {
            "available",
            "active",
            "in stock",
            "in_stock",
        }:
            return False
    return True


# ------------------------------------------------------------------
# Menu
# ------------------------------------------------------------------

@app.get("/")
def get_menu(subdomain: str = Query(...)):
    """
    Return the menu for a restaurant identified by its subdomain.
    """

    menu = MENUS.get(subdomain)

    if menu is None:
        logger.warning(
            "Menu lookup failed: restaurant not found | subdomain=%s",
            subdomain,
        )

        raise HTTPException(
            status_code=404,
            detail=f"Restaurant '{subdomain}' not found",
        )

    logger.info(
        "Menu requested | subdomain=%s | item_count=%s",
        subdomain,
        len(menu["items"]),
    )

    return {
        "restaurant_name": menu["restaurant_name"],
        "subdomain": subdomain,
        "items": menu["items"],
    }


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------

@app.get("/health")
def health_check(repository: OrderRepository = Depends(get_order_repository)):
    try:
        repository.health()
    except OrderStorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="Order storage is unavailable.") from exc
    return {
        "status": "ok",
        "service": "menu-backend",
    }


# ------------------------------------------------------------------
# Orders
# ------------------------------------------------------------------

@app.post(
    "/orders",
    status_code=201,
    dependencies=[Depends(require_menu_service_key)],
)
def create_order(
    order: OrderRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    repository: OrderRepository = Depends(get_order_repository),
):
    """
    Validate an order against the current menu and persist it
    for local development.

    Menu prices and variation prices are always authoritative.
    Client-submitted prices are never trusted.
    """

    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 128:
        raise HTTPException(status_code=400, detail="A valid idempotency key is required.")

    fingerprint = request_fingerprint(order.model_dump(mode="json"))
    try:
        replay = repository.get_idempotent_order(
            user_id=order.user_id,
            subdomain=order.subdomain,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
        )
    except IdempotencyConflict as exc:
        _log_order_event("order.idempotency_conflict", level=logging.WARNING)
        raise HTTPException(
            status_code=409,
            detail="The idempotency key was already used for a different order.",
        ) from exc
    except (OrderStorageUnavailable, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Order storage is temporarily unavailable.") from exc
    if replay is not None:
        _log_order_event("order.idempotent_replay", subdomain=order.subdomain)
        return replay

    logger.info(
        "Order creation requested | restaurant=%s | subdomain=%s | item_count=%s",
        order.restaurant_name,
        order.subdomain,
        len(order.items),
    )

    menu = MENUS.get(order.subdomain)

    if menu is None or menu["restaurant_name"] != order.restaurant_name:
        logger.warning(
            "Order rejected: invalid restaurant or subdomain | restaurant=%s | subdomain=%s",
            order.restaurant_name,
            order.subdomain,
        )

        raise HTTPException(
            status_code=400,
            detail="Restaurant or subdomain is invalid",
        )

    menu_items = {
        item["id"]: item
        for item in menu["items"]
    }

    confirmed_items = []
    subtotal = 0.0

    for submitted_item in order.items:

        menu_item = menu_items.get(
            submitted_item.item_id
        )

        if menu_item is None:
            logger.warning(
                "Order rejected: unknown item | item_id=%s",
                submitted_item.item_id,
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown item "
                    f"'{submitted_item.item_id}'"
                ),
            )

        if not _menu_item_is_available(menu_item):
            raise HTTPException(
                status_code=409,
                detail="Menu item is not currently available",
            )

        if submitted_item.title != menu_item["title"]:
            logger.warning(
                "Order rejected: item title mismatch | item_id=%s",
                submitted_item.item_id,
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    "Submitted item title "
                    "does not match the menu"
                ),
            )

        menu_variations = menu_item.get(
            "variations",
            [],
        )

        if not isinstance(menu_variations, list):
            logger.error(
                "Invalid menu variation data | item_id=%s",
                submitted_item.item_id,
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    "Menu variation data is invalid "
                    "for this item"
                ),
            )

        # ---------------------------------------------------------
        # Items WITH variations
        # ---------------------------------------------------------

        if menu_variations:

            if submitted_item.variation is None:
                logger.warning(
                    "Order rejected: missing variation | item_id=%s",
                    submitted_item.item_id,
                )

                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"A variation must be selected "
                        f"for '{menu_item['title']}'"
                    ),
                )

            if not isinstance(
                submitted_item.variation,
                dict,
            ):
                logger.warning(
                    "Order rejected: invalid variation payload | item_id=%s",
                    submitted_item.item_id,
                )

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Submitted variation "
                        "is invalid"
                    ),
                )

            submitted_variation_id = (
                submitted_item.variation.get("id")
            )

            if not submitted_variation_id:
                logger.warning(
                    "Order rejected: missing variation ID | item_id=%s",
                    submitted_item.item_id,
                )

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Submitted variation ID "
                        "is required"
                    ),
                )

            menu_variation = next(
                (
                    variation
                    for variation in menu_variations
                    if isinstance(variation, dict)
                    and variation.get("id")
                    == submitted_variation_id
                ),
                None,
            )

            if menu_variation is None:
                logger.warning(
                    "Order rejected: unavailable variation | item_id=%s | variation_id=%s",
                    submitted_item.item_id,
                    submitted_variation_id,
                )

                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Variation "
                        f"'{submitted_variation_id}' "
                        f"is not available for "
                        f"'{menu_item['title']}'"
                    ),
                )

            raw_variation_price = menu_variation.get(
                "price"
            )

            try:
                authoritative_price = float(
                    raw_variation_price
                )
            except (
                TypeError,
                ValueError,
            ):
                logger.error(
                    "Invalid variation pricing in menu | item_id=%s | variation_id=%s",
                    submitted_item.item_id,
                    submitted_variation_id,
                )

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Selected menu variation "
                        "has invalid pricing"
                    ),
                )

            if not isfinite(authoritative_price) or authoritative_price < 0:
                logger.error(
                    "Negative variation pricing in menu | item_id=%s | variation_id=%s",
                    submitted_item.item_id,
                    submitted_variation_id,
                )

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Selected menu variation "
                        "has invalid pricing"
                    ),
                )

            try:
                submitted_price = float(
                    submitted_item.base_price
                )
            except (
                TypeError,
                ValueError,
            ):
                logger.warning(
                    "Order rejected: invalid submitted price | item_id=%s",
                    submitted_item.item_id,
                )

                raise HTTPException(
                    status_code=400,
                    detail="Submitted item price is invalid",
                )

            if not isfinite(submitted_price):
                raise HTTPException(
                    status_code=400,
                    detail="Submitted item price is invalid",
                )

            if submitted_price != authoritative_price:
                logger.warning(
                    "Order rejected: price mismatch | item_id=%s | variation_id=%s | submitted=%s | authoritative=%s",
                    submitted_item.item_id,
                    submitted_variation_id,
                    submitted_price,
                    authoritative_price,
                )

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Submitted item price does not "
                        "match the selected menu variation"
                    ),
                )

            authoritative_variation = {
                "id": menu_variation["id"],
                "name": str(
                    menu_variation.get(
                        "name",
                        "",
                    )
                ),
                "price": str(
                    menu_variation["price"]
                ),
            }

        # ---------------------------------------------------------
        # Items WITHOUT variations
        # ---------------------------------------------------------

        else:

            if submitted_item.variation is not None:
                logger.warning(
                    "Order rejected: variation supplied for non-variation item | item_id=%s",
                    submitted_item.item_id,
                )

                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"'{menu_item['title']}' "
                        "does not have variations"
                    ),
                )

            try:
                submitted_price = float(submitted_item.base_price)
                authoritative_price = float(menu_item["base_price"])
            except (
                TypeError,
                ValueError,
                KeyError,
            ):
                logger.warning(
                    "Order rejected: invalid submitted price | item_id=%s",
                    submitted_item.item_id,
                )

                raise HTTPException(
                    status_code=400,
                    detail="Submitted item price is invalid",
                )

            if (
                not isfinite(submitted_price)
                or not isfinite(authoritative_price)
                or authoritative_price < 0
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Menu item has invalid pricing and cannot be ordered.",
                )

            if submitted_price != authoritative_price:
                logger.warning(
                    "Order rejected: price mismatch | item_id=%s | submitted=%s | authoritative=%s",
                    submitted_item.item_id,
                    submitted_price,
                    authoritative_price,
                )

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Submitted item price "
                        "does not match the menu"
                    ),
                )

            authoritative_variation = None

        # ---------------------------------------------------------
        # Build authoritative order item
        # ---------------------------------------------------------

        subtotal += (
            authoritative_price
            * submitted_item.quantity
        )
        if not isfinite(subtotal) or subtotal > 9_999_999_999.99:
            raise HTTPException(
                status_code=422,
                detail="Order total exceeds the supported range.",
            )

        confirmed_items.append(
            {
                "item_id": menu_item["id"],
                "title": menu_item["title"],
                "quantity": submitted_item.quantity,
                "base_price": authoritative_price,
                "variation": authoritative_variation,
            }
        )

    try:
        created_order, replayed = repository.create_order({
            "restaurant_name": menu["restaurant_name"],
            "subdomain": order.subdomain,
            "user_id": order.user_id,
            "idempotency_key": idempotency_key,
            "request_fingerprint": fingerprint,
            "items": confirmed_items,
            "subtotal": round(subtotal, 2),
        })
    except IdempotencyConflict as exc:
        _log_order_event("order.idempotency_conflict", level=logging.WARNING)
        raise HTTPException(
            status_code=409,
            detail="The idempotency key was already used for a different order.",
        ) from exc
    except (OrderStorageUnavailable, RuntimeError) as exc:
        _log_order_event("order.persistence_failure", level=logging.ERROR, subdomain=order.subdomain)
        raise HTTPException(
            status_code=503,
            detail="Order storage is temporarily unavailable.",
        ) from exc

    _log_order_event(
        "order.idempotent_replay" if replayed else "order.accepted",
        subdomain=order.subdomain,
        item_count=len(confirmed_items),
    )
    return created_order


# ------------------------------------------------------------------
# Order status
# ------------------------------------------------------------------

@app.get(
    "/orders/{order_id}",
    dependencies=[Depends(require_menu_service_key)],
)
def get_order(
    order_id: str,
    subdomain: str = Query(..., min_length=1),
    user_id: str = Query(..., min_length=1, max_length=128),
    repository: OrderRepository = Depends(get_order_repository),
):
    try:
        order = repository.get_order(order_id, user_id=user_id, subdomain=subdomain)
    except OrderStorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="Order storage is temporarily unavailable.") from exc

    if order is None:
        _log_order_event("order.lookup_not_found", level=logging.WARNING)

        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    _log_order_event("order.status_retrieved", status=order["status"])

    return order


# ------------------------------------------------------------------
# Order cancellation
# ------------------------------------------------------------------

@app.delete(
    "/orders/{order_id}",
    dependencies=[Depends(require_menu_service_key)],
)
def cancel_order(
    order_id: str,
    subdomain: str = Query(..., min_length=1),
    user_id: str = Query(..., min_length=1, max_length=128),
    repository: OrderRepository = Depends(get_order_repository),
):
    """
    Cancel an existing order while retaining it
    for later status lookup.
    """

    try:
        order = repository.get_order(order_id, user_id=user_id, subdomain=subdomain)
    except OrderStorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="Order storage is temporarily unavailable.") from exc

    if order is None:
        _log_order_event("order.cancellation_not_found", level=logging.WARNING)

        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    try:
        order = repository.cancel_order(order_id, user_id=user_id, subdomain=subdomain)
    except OrderStorageUnavailable as exc:
        raise HTTPException(status_code=503, detail="Order storage is temporarily unavailable.") from exc
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    _log_order_event("order.cancellation_confirmed", subdomain=subdomain)

    return order


# ------------------------------------------------------------------
# Local development entry point
# ------------------------------------------------------------------

def main():
    import uvicorn

    logger.info("Starting menu backend on port %s", PORT)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
    )


if __name__ == "__main__":
    main()
