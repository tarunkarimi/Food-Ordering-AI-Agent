"""Authenticated persistent-cart API."""

import json
import logging
import re

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.agents.tools.cart import _fetch_menu_items, _valid_price, _valid_quantity
from src.agents.tools.order import cancel_order
from src.api.dependencies import AuthenticatedSession, get_current_session
from src.configs.config import config
from src.db.database import get_db
from src.services.cart import (
    add_item,
    clear_cart,
    get_cart,
    remove_item,
    update_item,
)
from src.services.order_history import (
    create_order_history,
    get_order_history,
    update_order_history_status,
)
from src.services.ordering_intelligence import is_menu_item_available
from src.services.menu_backend import menu_service_headers
from src.observability import log_event
from src.db.models.order_operation import OrderOperation
from src.services.order_operations import (
    OperationConflict,
    begin_operation,
    fingerprint,
    get_order_operation,
    mark_operation_complete,
    mark_operation_retryable,
    mark_upstream_confirmed,
    operation_response,
    update_operation_request,
)

import requests


router = APIRouter()
logger = logging.getLogger(__name__)


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


class CartCheckoutRequest(BaseModel):
    confirm: bool = Field(
        ...,
        description="Explicit customer confirmation to place the order.",
    )


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
    if not is_menu_item_available(menu_item):
        raise HTTPException(
            status_code=409,
            detail="That menu item is not currently available.",
        )

    if not _valid_quantity(quantity):
        raise HTTPException(
            status_code=422,
            detail="Quantity must be greater than zero.",
        )

    raw_price = menu_item.get(
        "base_price",
        menu_item.get("price"),
    )

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
        variation_id.strip()
        if variation_id is not None
        else None
    )

    variation_name = None
    variation_price = None

    if variations and normalized_variation_id:
        selected_variation = next(
            (
                variation
                for variation in variations
                if (
                    isinstance(variation, dict)
                    and str(variation.get("id", ""))
                    == normalized_variation_id
                )
            ),
            None,
        )

        if selected_variation is None:
            raise HTTPException(
                status_code=400,
                detail="That variation is not available for this item.",
            )

        raw_variation_price = selected_variation.get("price")

        try:
            variation_price = float(raw_variation_price)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=409,
                detail="That menu variation has invalid pricing.",
            )

        if not _valid_price(variation_price):
            raise HTTPException(
                status_code=409,
                detail="That menu variation has invalid pricing.",
            )

        variation_name = str(
            selected_variation.get("name", "")
        ).strip()
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

        line_total = (
            float(item.unit_price)
            * item.quantity
        )

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

    total = sum(
        item["line_total"]
        for item in items
    )

    return {
        "id": cart.id,
        "restaurant_name": cart.restaurant_name,
        "subdomain": cart.subdomain,
        "items": items,
        "total": total,
    }


def _cart_checkout_selection(cart):
    if cart is None or not cart.items:
        return None
    return {
        "restaurant_name": cart.restaurant_name,
        "subdomain": cart.subdomain,
        "items": [
            {
                "item_id": item.item_id,
                "title": item.title,
                "quantity": item.quantity,
                "variation_id": item.variation_id,
            }
            for item in cart.items
        ],
    }


def _build_checkout_items(cart, menu_items):
    """Revalidate persistent cart items and build the order payload."""
    order_items = []

    for cart_item in cart.items:
        menu_item = _find_menu_item(
            menu_items,
            item_id=cart_item.item_id,
            title=cart_item.title,
        )

        if menu_item is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"'{cart_item.title}' is no longer "
                    "available on the current menu."
                ),
            )

        authoritative = _authoritative_item(
            menu_item,
            item_id=cart_item.item_id,
            title=cart_item.title,
            quantity=cart_item.quantity,
            variation_id=cart_item.variation_id,
        )

        if authoritative["item_key"] != cart_item.item_key:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"The variation for '{cart_item.title}' "
                    "is no longer available."
                ),
            )

        stored_price = round(float(cart_item.unit_price), 2)
        current_price = round(float(authoritative["unit_price"]), 2)

        if stored_price != current_price:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"The price for '{cart_item.title}' "
                    f"has changed from {stored_price:.2f} "
                    f"to {current_price:.2f}."
                ),
            )
        order_items.append(
            {
                "item_id": authoritative["item_id"],
                "title": authoritative["title"],
                "quantity": authoritative["quantity"],
                "base_price": authoritative["unit_price"],
                "variation": (
                    {
                        "id": authoritative["variation_id"],
                        "name": authoritative["variation_name"],
                        "price": authoritative["variation_price"],
                    }
                    if authoritative["variation_id"] is not None
                    else None
                ),
            }
        )

    if not order_items:
        raise HTTPException(
            status_code=400,
            detail="Cannot place an empty cart.",
        )

    return order_items


@router.get("")
def get_authenticated_cart(
    auth: AuthenticatedSession = Depends(
        get_current_session
    ),
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
    auth: AuthenticatedSession = Depends(
        get_current_session
    ),
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
    auth: AuthenticatedSession = Depends(
        get_current_session
    ),
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
            detail=(
                "Cart item key does not match "
                "the requested item."
            ),
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
    auth: AuthenticatedSession = Depends(
        get_current_session
    ),
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
    auth: AuthenticatedSession = Depends(
        get_current_session
    ),
    db: Session = Depends(get_db),
):
    return _serialize_cart(
        clear_cart(
            db,
            user_id=auth.user.id,
        )
    )


@router.post("/checkout")
def checkout_authenticated_cart(
    request: CartCheckoutRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth: AuthenticatedSession = Depends(
        get_current_session
    ),
    db: Session = Depends(get_db),
):
    if not request.confirm:
        raise HTTPException(
            status_code=400,
            detail=(
                "Explicit confirmation is required "
                "before placing the order."
            ),
        )

    if not isinstance(idempotency_key, str) or not re.fullmatch(
        r"[A-Za-z0-9._:-]{8,128}", idempotency_key
    ):
        raise HTTPException(status_code=400, detail="A valid checkout idempotency key is required.")

    existing_operation = get_order_operation(
        db, user_id=auth.user.id, idempotency_key=idempotency_key,
    )
    creating_intent = existing_operation is None
    if existing_operation is not None and existing_operation.operation_type != "checkout":
        raise HTTPException(status_code=409, detail="Checkout key conflicts with another order operation.")
    if existing_operation is not None and existing_operation.status == "completed":
        completed_cart = get_cart(db, user_id=auth.user.id)
        if completed_cart is not None and completed_cart.items:
            raise HTTPException(
                status_code=409,
                detail="This checkout key was already completed. Start a new checkout for the current cart.",
                headers={"X-Checkout-Intent-Completed": "true"},
            )
        cached = operation_response(existing_operation)
        if cached is None:
            raise HTTPException(status_code=503, detail="Checkout result is being reconciled. Retry with the same key.")
        cached["cart"] = _serialize_cart(completed_cart)
        log_event(logger, "checkout.idempotent_replay", operation_id=existing_operation.id)
        return cached

    cart = get_cart(
        db,
        user_id=auth.user.id,
    )

    if (cart is None or not cart.items) and existing_operation is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot place an empty cart.",
        )

    cart_selection = _cart_checkout_selection(cart)

    if existing_operation is not None and cart_selection is not None:
        if existing_operation.request_fingerprint != fingerprint(cart_selection):
            raise HTTPException(status_code=409, detail="The checkout key belongs to a different cart. Start a new checkout.")

    operation = existing_operation
    order_items = []
    payload = None
    if operation is None:
        if cart is None or not cart.items or cart_selection is None:
            raise HTTPException(status_code=400, detail="Cannot place an empty cart.")
        # Commit checkout intent before the mutating downstream order call.
        try:
            operation = begin_operation(
                db,
                user_id=auth.user.id,
                operation_type="checkout",
                idempotency_key=idempotency_key,
                order_id=None,
                subdomain=cart.subdomain,
                payload={"_phase": "intent", "selection": cart_selection},
                fingerprint_payload=cart_selection,
            )
        except OperationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        log_event(logger, "checkout.intent_created", operation_id=operation.id)

    if not creating_intent:
        log_event(
            logger,
            "checkout.reconciliation_attempt",
            operation_id=operation.id,
            attempt=operation.attempts,
            status=operation.status,
        )

    if operation.status == "upstream_confirmed":
        result = operation_response(operation)
        payload = json.loads(operation.request_json)
        order_items = payload.get("items", [])
    elif operation.request_json and '"_phase"' not in operation.request_json:
        payload = json.loads(operation.request_json)
        order_items = payload.get("items", [])

    if operation.status != "upstream_confirmed" and payload is None:
        if cart is None or not cart.items:
            raise HTTPException(status_code=503, detail="Checkout intent is pending. Restore the cart and retry with the same key.")
        db.commit()
        menu_items, menu_error = _fetch_menu_items({"subdomain": cart.subdomain})
        if menu_error:
            mark_operation_retryable(db, operation, error_code="menu_unavailable")
            raise HTTPException(status_code=503, detail=menu_error)
        order_items = _build_checkout_items(cart, menu_items)
        payload = {
            "restaurant_name": cart.restaurant_name,
            "subdomain": cart.subdomain,
            "user_id": str(auth.user.id),
            "items": order_items,
        }
        update_operation_request(db, operation, payload=payload)

    order_url = f"{config.MENU_BACKEND_URL.rstrip('/')}/orders"

    if operation.status != "upstream_confirmed":
        try:
            # The outbox row and normalized payload are committed already;
            # release the refresh transaction before network I/O.
            db.commit()
            log_event(logger, "checkout.upstream_attempt", operation_id=operation.id)
            response = requests.post(
                order_url,
                json=payload,
                headers={
                    **menu_service_headers(),
                    "Idempotency-Key": idempotency_key,
                },
                timeout=10,
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Order API response is malformed.")
            order_id = result.get("order_id")
            status = result.get("status")
            subtotal = result.get("subtotal")
            if (
                not isinstance(order_id, str)
                or not order_id
                or status != "confirmed"
                or not _valid_price(subtotal)
            ):
                # Leave the durable intent retryable. The same upstream
                # idempotency key can then recover a valid authoritative result.
                raise ValueError("Order API response is malformed.")
            mark_upstream_confirmed(
                db,
                operation,
                order_id=order_id,
                response=result,
            )
            log_event(logger, "checkout.upstream_accepted", operation_id=operation.id)
        except requests.Timeout as exc:
            mark_operation_retryable(db, operation, error_code="upstream_timeout")
            log_event(logger, "checkout.upstream_retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="timeout")
            raise HTTPException(status_code=503, detail="Ordering service timed out. Retry checkout with the same key.") from exc
        except requests.ConnectionError as exc:
            mark_operation_retryable(db, operation, error_code="upstream_unavailable")
            log_event(logger, "checkout.upstream_retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="connection")
            raise HTTPException(status_code=503, detail="Ordering service is unavailable. Retry checkout with the same key.") from exc
        except requests.RequestException as exc:
            mark_operation_retryable(db, operation, error_code="upstream_error")
            log_event(logger, "checkout.upstream_retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="request")
            raise HTTPException(status_code=502, detail="Ordering service returned an error. Retry checkout with the same key.") from exc
        except (ValueError, TypeError, AttributeError) as exc:
            mark_operation_retryable(db, operation, error_code="invalid_upstream_response")
            log_event(logger, "checkout.upstream_retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="invalid_response")
            raise HTTPException(status_code=502, detail="Ordering service returned an invalid response.") from exc

    if operation.status == "upstream_confirmed":
        result = operation_response(operation)
    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="Order result is being reconciled. Retry checkout with the same key.")

    order_id = result.get("order_id")
    status = result.get("status")
    subtotal = result.get("subtotal")
    if not isinstance(order_id, str) or not order_id or status != "confirmed" or not _valid_price(subtotal):
        raise HTTPException(status_code=502, detail="Ordering service returned an invalid order result.")
    total_items = sum(item["quantity"] for item in order_items)
    response_body = {
        "success": True,
        "order_id": order_id,
        "status": status,
        "subtotal": float(subtotal),
        "total_items": total_items,
        "cart": None,
    }
    try:
        create_order_history(
            db,
            user_id=auth.user.id,
            order_id=order_id,
            restaurant_name=payload["restaurant_name"],
            subdomain=payload["subdomain"],
            status=status,
            subtotal=float(subtotal),
            total_items=total_items,
            items=order_items,
        )
        current_cart = get_cart(db, user_id=auth.user.id)
        if fingerprint(_cart_checkout_selection(current_cart) or {}) == operation.request_fingerprint:
            clear_cart(db, user_id=auth.user.id, commit=False)
            response_body["cart"] = {
                "id": current_cart.id if current_cart else None,
                "restaurant_name": payload["restaurant_name"],
                "subdomain": payload["subdomain"],
                "items": [],
                "total": 0,
            }
        else:
            response_body["cart"] = _serialize_cart(current_cart)
        operation.order_id = order_id
        mark_operation_complete(db, operation, response=response_body, commit=False)
        db.commit()
    except Exception as exc:
        db.rollback()
        log_event(logger, "checkout.reconciliation_failure", level=logging.ERROR, operation_id=operation.id)
        raise HTTPException(
            status_code=503,
            detail="The ordering service confirmed the order; order history is being reconciled. Retry with the same checkout key.",
        ) from exc
    log_event(logger, "checkout.reconciliation_succeeded", operation_id=operation.id)
    return response_body

@router.delete("/orders/{order_id}")
def cancel_authenticated_order(
    order_id: str,
    auth: AuthenticatedSession = Depends(
        get_current_session
    ),
    db: Session = Depends(get_db),
):
    """
    Cancel an authenticated user's order.

    The authenticated session is validated before the existing order
    cancellation tool is invoked. The menu backend remains the source
    of truth for the cancellation itself.
    """
    requested_order_id = order_id.strip()

    if not requested_order_id:
        raise HTTPException(
            status_code=400,
            detail="Order ID is required.",
        )

    owned_order = get_order_history(
        db,
        user_id=auth.user.id,
        order_id=requested_order_id,
    )
    if owned_order is None:
        raise HTTPException(
            status_code=404,
            detail="Order was not found.",
        )
    if not isinstance(owned_order.subdomain, str) or not owned_order.subdomain.strip():
        raise HTTPException(
            status_code=409,
            detail="Unable to verify the order's restaurant identity.",
        )

    cancellation_key = f"cancel:{auth.user.id}:{requested_order_id}"
    cancellation_payload = {
        "order_id": requested_order_id,
        "subdomain": owned_order.subdomain,
        "restaurant_name": owned_order.restaurant_name,
    }
    try:
        operation = begin_operation(
            db,
            user_id=auth.user.id,
            operation_type="cancellation",
            idempotency_key=cancellation_key,
            order_id=requested_order_id,
            subdomain=owned_order.subdomain,
            payload=cancellation_payload,
        )
    except OperationConflict as exc:
        log_event(logger, "cancellation.idempotency_conflict", level=logging.WARNING)
        raise HTTPException(status_code=409, detail="Cancellation key conflicts with another order operation.") from exc

    if operation.attempts == 1:
        log_event(logger, "cancellation.intent_created", operation_id=operation.id)
    else:
        log_event(logger, "cancellation.reconciliation_attempt", operation_id=operation.id, attempt=operation.attempts)

    if operation.status == "completed":
        return operation_response(operation) or {
            "success": True,
            "order_id": requested_order_id,
            "status": "cancelled",
        }

    order_url = (
        f"{config.MENU_BACKEND_URL.rstrip('/')}"
        f"/orders/{requests.utils.quote(requested_order_id, safe='')}"
    )

    order = operation_response(operation) if operation.status == "upstream_confirmed" else None
    try:
        if order is None:
            # Persisted cancellation intent survives the request; keep the
            # database transaction short while waiting on the menu service.
            db.commit()
            log_event(logger, "cancellation.upstream_attempt", operation_id=operation.id)
            response = requests.delete(
                order_url,
                params={
                    "subdomain": owned_order.subdomain,
                    "user_id": str(auth.user.id),
                },
                headers=menu_service_headers(),
                timeout=10,
            )

            if response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Order {requested_order_id} was not found.",
                )

            response.raise_for_status()
            order = response.json()

        if (
            not isinstance(order, dict)
            or not isinstance(
                order.get("order_id"),
                str,
            )
            or order.get("order_id") != requested_order_id
            or order.get("restaurant_name") != owned_order.restaurant_name
            or order.get("subdomain") != owned_order.subdomain
        ):
            raise ValueError(
                "Order API response is missing order_id"
            )

        if order.get("status") != "cancelled":
            raise ValueError(
                "Order API response did not confirm cancellation"
            )

        if operation.status != "upstream_confirmed":
            mark_upstream_confirmed(
                db,
                operation,
                order_id=requested_order_id,
                response=order,
            )
            log_event(logger, "cancellation.upstream_confirmed", operation_id=operation.id)

    except HTTPException:
        raise

    except requests.Timeout as exc:
        mark_operation_retryable(db, operation, error_code="cancel_timeout")
        log_event(logger, "cancellation.retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="timeout")
        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to cancel order: the ordering "
                "service timed out."
            ),
        ) from exc

    except requests.ConnectionError as exc:
        mark_operation_retryable(db, operation, error_code="cancel_unavailable")
        log_event(logger, "cancellation.retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="connection")
        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to cancel order: the ordering "
                "service is unavailable."
            ),
        ) from exc

    except requests.RequestException as exc:
        mark_operation_retryable(db, operation, error_code="cancel_upstream_error")
        log_event(logger, "cancellation.retryable_failure", level=logging.WARNING, operation_id=operation.id, error_type="request")
        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to cancel order: the ordering "
                "service returned an error."
            ),
        ) from exc

    except (ValueError, TypeError, AttributeError) as exc:
        log_event(logger, "cancellation.invalid_upstream_response", level=logging.WARNING, operation_id=operation.id)
        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to cancel order: the ordering "
                "service returned an invalid response."
            ),
        ) from exc

    try:
        update_order_history_status(
            db,
            user_id=auth.user.id,
            order_id=order["order_id"],
            status="cancelled",
        )
        cancellation_result = {
        "success": True,
        "order_id": order["order_id"],
        "status": "cancelled",
        }
        mark_operation_complete(db, operation, response=cancellation_result)
        log_event(logger, "cancellation.reconciliation_succeeded", operation_id=operation.id)
        return cancellation_result
    except Exception as exc:
        db.rollback()
        log_event(logger, "cancellation.reconciliation_failure", level=logging.ERROR, operation_id=operation.id)
        raise HTTPException(
            status_code=503,
            detail="The ordering service confirmed cancellation; order history is being reconciled. Retry the cancellation request.",
        ) from exc
