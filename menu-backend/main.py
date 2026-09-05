from typing import Any, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field


app = FastAPI(
    title="Food Ordering Menu Backend",
    description="Local development menu service for the Food Ordering AI Agent",
    version="1.0.0",
)


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


# Local-development storage.
# Replace this with a database in a deployed service.
ORDERS: dict[str, dict[str, Any]] = {}


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


@app.get("/")
def get_menu(subdomain: str = Query(...)):
    """
    Return the menu for a restaurant identified by its subdomain.
    """

    menu = MENUS.get(subdomain)

    if menu is None:
        raise HTTPException(
            status_code=404,
            detail=f"Restaurant '{subdomain}' not found",
        )

    return {
        "restaurant_name": menu["restaurant_name"],
        "subdomain": subdomain,
        "items": menu["items"],
    }


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "menu-backend",
    }


@app.post("/orders", status_code=201)
def create_order(order: OrderRequest):
    """
    Validate an order against the current menu and persist it
    for local development.

    Menu prices and variation prices are always authoritative.
    Client-submitted prices are never trusted.
    """

    menu = MENUS.get(order.subdomain)

    if menu is None or menu["restaurant_name"] != order.restaurant_name:
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
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown item "
                    f"'{submitted_item.item_id}'"
                ),
            )

        if submitted_item.title != menu_item["title"]:
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
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Selected menu variation "
                        "has invalid pricing"
                    ),
                )

            if authoritative_price < 0:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Selected menu variation "
                        "has invalid pricing"
                    ),
                )

            # The submitted price is checked against
            # the authoritative variation price.
            # This prevents tampering while allowing
            # numeric/string representations such as
            # 280 and "280".
            try:
                submitted_price = float(
                    submitted_item.base_price
                )
            except (
                TypeError,
                ValueError,
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Submitted item price is invalid",
                )

            if submitted_price != authoritative_price:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Submitted item price does not "
                        "match the selected menu variation"
                    ),
                )

            # Store the authoritative variation from
            # the menu rather than trusting the client.
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
                raise HTTPException(
                    status_code=400,
                    detail="Submitted item price is invalid",
                )

            authoritative_price = float(
                menu_item["base_price"]
            )

            if submitted_price != authoritative_price:
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

    return created_order


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = ORDERS.get(order_id)

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    return order


@app.delete("/orders/{order_id}")
def cancel_order(order_id: str):
    """
    Cancel an existing order while retaining it
    for later status lookup.
    """

    order = ORDERS.get(order_id)

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    if order["status"] == "cancelled":
        raise HTTPException(
            status_code=400,
            detail="Order is already cancelled",
        )

    order["status"] = "cancelled"

    return order