import logging
import os
from typing import Any, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Application configuration
# ------------------------------------------------------------------

PORT = int(os.getenv("PORT", "8000"))


# ------------------------------------------------------------------
# Application
# ------------------------------------------------------------------

app = FastAPI(
    title="Food Ordering Menu Backend",
    description="Menu and order service for the Food Ordering AI Agent",
    version="1.0.0",
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
# Local-development storage.
# Replace this with a database in a deployed service.
# ------------------------------------------------------------------

ORDERS: dict[str, dict[str, Any]] = {}


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
    items: list[OrderItemRequest] = Field(min_length=1)


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
def health_check():
    return {
        "status": "ok",
        "service": "menu-backend",
    }


# ------------------------------------------------------------------
# Orders
# ------------------------------------------------------------------

@app.post("/orders", status_code=201)
def create_order(order: OrderRequest):
    """
    Validate an order against the current menu and persist it
    for local development.

    Menu prices and variation prices are always authoritative.
    Client-submitted prices are never trusted.
    """

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

            if authoritative_price < 0:
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

            authoritative_price = float(
                menu_item["base_price"]
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

        confirmed_items.append(
            {
                "item_id": menu_item["id"],
                "title": menu_item["title"],
                "quantity": submitted_item.quantity,
                "base_price": authoritative_price,
                "variation": authoritative_variation,
            }
        )

    order_id = (
        f"ORD-{uuid4().hex[:8].upper()}"
    )

    created_order = {
        "order_id": order_id,
        "restaurant_name": menu["restaurant_name"],
        "subdomain": order.subdomain,
        "items": confirmed_items,
        "subtotal": subtotal,
        "status": "confirmed",
    }

    ORDERS[order_id] = created_order

    logger.info(
        "Order created successfully | order_id=%s | subtotal=%.2f | item_count=%s",
        order_id,
        subtotal,
        len(confirmed_items),
    )

    return created_order


# ------------------------------------------------------------------
# Order status
# ------------------------------------------------------------------

@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = ORDERS.get(order_id)

    if order is None:
        logger.warning(
            "Order lookup failed: order not found | order_id=%s",
            order_id,
        )

        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    logger.info(
        "Order retrieved | order_id=%s | status=%s",
        order_id,
        order["status"],
    )

    return order


# ------------------------------------------------------------------
# Order cancellation
# ------------------------------------------------------------------

@app.delete("/orders/{order_id}")
def cancel_order(order_id: str):
    """
    Cancel an existing order while retaining it
    for later status lookup.
    """

    order = ORDERS.get(order_id)

    if order is None:
        logger.warning(
            "Order cancellation failed: order not found | order_id=%s",
            order_id,
        )

        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    if order["status"] == "cancelled":
        logger.warning(
            "Order cancellation rejected: already cancelled | order_id=%s",
            order_id,
        )

        raise HTTPException(
            status_code=400,
            detail="Order is already cancelled",
        )

    order["status"] = "cancelled"

    logger.info(
        "Order cancelled | order_id=%s",
        order_id,
    )

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