"""Authenticated persistent-cart API."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.agents.tools.cart import _fetch_menu_items, _valid_price, _valid_quantity
from src.api.dependencies import AuthenticatedSession, get_current_session
from src.db.database import get_db
from src.services.cart import (
    add_item,
    clear_cart,
    get_cart,
    remove_item,
    update_item,
)

router = APIRouter()


class CartItemRequest(BaseModel):
    restaurant_name: str = Field(min_length=1, max_length=255)
    subdomain: str = Field(min_length=1, max_length=255)
    item_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    quantity: int = Field(gt=0)
    variation_id: str | None = Field(default=None, max_length=255)


class CartItemUpdateRequest(BaseModel):
    restaurant_name: str = Field(min_length=1, max_length=255)
    subdomain: str = Field(min_length=1, max_length=255)
    item_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    quantity: int = Field(gt=0)
    variation_id: str | None = Field(default=None, max_length=255)


def _find_menu_item(items, *, item_id: str, title: str):
    normalized_id = item_id.strip()
    normalized_title = title.strip().casefold()

    for item in items:
        if not isinstance(item, dict):
            continue

        if (
            str(item.get("id", "")) == normalized_id
            and str(item.get("title", "")).strip().casefold()
            == normalized_title
        ):
            return item

    return None


def _authoritative_item(
    menu_item: dict,
    *,
    item_id: str,
    title: str,
    quantity: int,
    variation_id: str | None,
):
    if not _valid_quantity(quantity):
        raise HTTPException(
            status_code=422,
            detail="Quantity must be greater than zero.",
        )

    raw_price = menu_item.get("base_price", menu_item.get("price"))

    if not _valid_price(raw_price):
        raise HTTPException(
            status_code=409,
            detail="That menu item has invalid pricing and cannot be added.",
        )

    authoritative_price = float(raw_price)

    variations = menu_item.get("variations", [])

    if not isinstance(variations, list):
        raise HTTPException(
            status_code=409,
            detail="That item has invalid variation data on the current menu.",
        )

    normalized_variation_id = (
        variation_id.strip() if variation_id is not None else None
    )

    variation_name = None
    variation_price = None

    if variations and normalized_variation_id:
        selected_variation = next(
            (
                variation
                for variation in variations
                if isinstance(variation, dict)
                and str(variation.get("id", "")) == normalized_variation_id
            ),
            None,
        )

        if selected_variation is None:
            raise HTTPException(
                status_code=400,
                detail="That variation is not available for this item.",
            )

        raw_variation_price = selected_variation.get("price")

        if not _valid_price(raw_variation_price):
            raise HTTPException(
                status_code=409,
                detail="That menu variation has invalid pricing.",
            )

        variation_name = str(selected_variation.get("name", "")).strip()
        variation_price = float(raw_variation_price)
        authoritative_price = variation_price

    elif variations and not normalized_variation_id:
        raise HTTPException(
            status_code=400,
            detail="A valid variation must be selected for this item.",
        )

    elif not variations:
        normalized_variation_id = None

    item_key = (
        f"{item_id.strip()}|"
        f"{normalized_variation_id or 'no_variant'}"
    )

    return {
        "item_key": item_key,
        "item_id": item_id.strip(),
        "title": str(menu_item.get("title", "")).strip(),
        "quantity": quantity,
        "unit_price": authoritative_price,
        "variation_id": normalized_variation_id,
        "variation_name": variation_name,
        "variation_price": variation_price,
    }


def _fetch_authoritative(
    *,
    restaurant_name: str,
    subdomain: str,
    item_id: str,
    title: str,
    quantity: int,
    variation_id: str | None,
):
    items, error = _fetch_menu_items(
        {
            "subdomain": subdomain,
        }
    )

    if error:
        raise HTTPException(
            status_code=503,
            detail=error,
        )

    menu_item = _find_menu_item(
        items,
        item_id=item_id,
        title=title,
    )

    if menu_item is None:
        raise HTTPException(
            status_code=400,
            detail="That item is not available on the current menu.",
        )

    return _authoritative_item(
        menu_item,
        item_id=item_id,
        title=title,
        quantity=quantity,
        variation_id=variation_id,
    )


def _serialize_cart(cart):
    if cart is None:
        return {
            "id": None,
            "restaurant_name": None,
            "subdomain": None,
            "items": [],
            "total": 0.0,
        }

    items = []

    for item in cart.items:
        variation = None

        if item.variation_id is not None:
            variation = {
                "id": item.variation_id,
                "name": item.variation_name,
                "price": float(item.variation_price),
            }

        line_total = float(item.unit_price) * item.quantity

        items.append(
            {
                "id": item.id,
                "item_key": item.item_key,
                "item_id": item.item_id,
                "title": item.title,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "variation": variation,
                "line_total": line_total,
            }
        )

    total = sum(item["line_total"] for item in items)

    return {
        "id": cart.id,
        "restaurant_name": cart.restaurant_name,
        "subdomain": cart.subdomain,
        "items": items,
        "total": total,
    }


@router.get("")
def get_authenticated_cart(
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    return _serialize_cart(
        get_cart(
            db,
            user_id=auth.user.id,
        )
    )


@router.post("/items")
def add_authenticated_cart_item(
    request: CartItemRequest,
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    authoritative = _fetch_authoritative(
        restaurant_name=request.restaurant_name,
        subdomain=request.subdomain,
        item_id=request.item_id,
        title=request.title,
        quantity=request.quantity,
        variation_id=request.variation_id,
    )

    try:
        cart = add_item(
            db,
            user_id=auth.user.id,
            restaurant_name=request.restaurant_name.strip(),
            subdomain=request.subdomain.strip(),
            **authoritative,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return _serialize_cart(cart)


@router.patch("/items/{item_key:path}")
def update_authenticated_cart_item(
    item_key: str,
    request: CartItemUpdateRequest,
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    authoritative = _fetch_authoritative(
        restaurant_name=request.restaurant_name,
        subdomain=request.subdomain,
        item_id=request.item_id,
        title=request.title,
        quantity=request.quantity,
        variation_id=request.variation_id,
    )

    if authoritative["item_key"] != item_key:
        raise HTTPException(
            status_code=400,
            detail="Cart item key does not match the requested item.",
        )

    try:
        cart = update_item(
            db,
            user_id=auth.user.id,
            item_key=item_key,
            quantity=request.quantity,
            unit_price=authoritative["unit_price"],
            title=authoritative["title"],
            variation_name=authoritative["variation_name"],
            variation_price=authoritative["variation_price"],
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    return _serialize_cart(cart)


@router.delete("/items/{item_key:path}")
def delete_authenticated_cart_item(
    item_key: str,
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    try:
        cart = remove_item(
            db,
            user_id=auth.user.id,
            item_key=item_key,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    return _serialize_cart(cart)


@router.delete("")
def clear_authenticated_cart(
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    return _serialize_cart(
        clear_cart(
            db,
            user_id=auth.user.id,
        )
    )
