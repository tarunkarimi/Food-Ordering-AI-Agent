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
                "variations": [],
            },
            {
                "id": "item-002",
                "title": "Paneer Butter Masala",
                "description": "Paneer cooked in a rich tomato and butter gravy.",
                "base_price": 180.0,
                "variations": [],
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
                "variations": [],
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

# Local-development storage. Replace this with a database in a deployed service.
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
    """Validate an order against the menu and persist it for local development."""
    menu = MENUS.get(order.subdomain)
    if menu is None or menu["restaurant_name"] != order.restaurant_name:
        raise HTTPException(status_code=400, detail="Restaurant or subdomain is invalid")

    menu_items = {item["id"]: item for item in menu["items"]}
    confirmed_items = []
    subtotal = 0.0

    for submitted_item in order.items:
        menu_item = menu_items.get(submitted_item.item_id)
        if menu_item is None:
            raise HTTPException(status_code=400, detail=f"Unknown item '{submitted_item.item_id}'")
        if submitted_item.title != menu_item["title"]:
            raise HTTPException(status_code=400, detail="Submitted item title does not match the menu")
        if submitted_item.base_price != menu_item["base_price"]:
            raise HTTPException(status_code=400, detail="Submitted item price does not match the menu")

        authoritative_price = menu_item["base_price"]
        subtotal += authoritative_price * submitted_item.quantity
        confirmed_items.append({
            "item_id": menu_item["id"],
            "title": menu_item["title"],
            "quantity": submitted_item.quantity,
            "base_price": authoritative_price,
            "variation": submitted_item.variation,
        })

    order_id = f"ORD-{uuid4().hex[:8].upper()}"
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
        raise HTTPException(status_code=404, detail="Order not found")
    return order
