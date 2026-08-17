from fastapi import FastAPI, HTTPException, Query

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