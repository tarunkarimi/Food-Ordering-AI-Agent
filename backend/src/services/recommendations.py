"""Context-aware recommendation services."""

from typing import Any

from sqlalchemy.orm import Session

from src.services.order_history import list_order_history
from src.services.user_preferences import get_user_preferences


def _normalize(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _item_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("title"),
        item.get("description"),
        item.get("category"),
        item.get("cuisine"),
        item.get("dietary"),
        item.get("tags"),
        item.get("spice_level"),
    ]

    return " ".join(
        str(part)
        for part in parts
        if part is not None
    ).lower()


def _menu_item_price(item: dict[str, Any]) -> float | None:
    raw_price = item.get("base_price")

    try:
        price = float(raw_price)
    except (TypeError, ValueError):
        return None

    if price < 0:
        return None

    return price


def _matches_dietary_preference(
    item: dict[str, Any],
    dietary_preference: str | None,
) -> bool:
    preference = _normalize(dietary_preference)

    if not preference:
        return True

    text = _item_text(item)

    if "vegetarian" in preference or preference in {"veg", "vegetarian"}:
        explicit_non_veg = (
            "chicken" in text
            or "mutton" in text
            or "lamb" in text
            or "fish" in text
            or "prawn" in text
            or "prawns" in text
            or "seafood" in text
            or "egg" in text
            or "beef" in text
            or "pork" in text
        )

        explicit_veg = (
            "vegetarian" in text
            or "veg" in text
        )

        if explicit_non_veg and not explicit_veg:
            return False

    return True


def _score_item(
    item: dict[str, Any],
    *,
    cuisine_preference: str | None,
    spice_level: str | None,
    dietary_preference: str | None,
    meal_preference: str | None,
    history_counts: dict[str, int],
) -> tuple[int, list[str]]:
    text = _item_text(item)
    title = _normalize(item.get("title"))

    score = 0
    reasons: list[str] = []

    cuisine = _normalize(cuisine_preference)
    if cuisine and cuisine in text:
        score += 5
        reasons.append("matches your cuisine preference")

    spice = _normalize(spice_level)
    if spice and spice in text:
        score += 4
        reasons.append("matches your spice preference")

    meal = _normalize(meal_preference)
    if meal and meal in text:
        score += 3
        reasons.append("matches your meal preference")

    if dietary_preference:
        score += 4
        reasons.append("fits your dietary preference")

    history_count = history_counts.get(title, 0)

    if history_count:
        score += min(history_count * 3, 9)
        reasons.append("similar to what you have ordered before")

    return score, reasons


def get_personalized_recommendations(
    db: Session,
    *,
    user_id: int,
    menu_items: list[dict[str, Any]],
    limit: int = 5,
) -> dict[str, Any]:
    """Rank current menu items using explicit preferences and order history.

    Current menu data is authoritative. This function never mutates the
    cart and never uses historical prices.
    """

    preferences = get_user_preferences(db, user_id=user_id)

    cuisine_preference = (
        preferences.cuisine_preference
        if preferences is not None
        else None
    )
    spice_level = (
        preferences.spice_level
        if preferences is not None
        else None
    )
    dietary_preference = (
        preferences.dietary_preference
        if preferences is not None
        else None
    )
    meal_preference = (
        preferences.meal_preference
        if preferences is not None
        else None
    )

    orders = list_order_history(
        db,
        user_id=user_id,
        limit=20,
        offset=0,
    )

    history_counts: dict[str, int] = {}

    import json

    for order in orders:
        try:
            items = json.loads(order.items_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            title = _normalize(
                item.get("title")
                or item.get("item_title")
                or item.get("name")
            )

            if title:
                history_counts[title] = history_counts.get(title, 0) + 1

    recommendations: list[dict[str, Any]] = []

    for item in menu_items:
        if not isinstance(item, dict):
            continue

        title = str(item.get("title") or "").strip()

        if not title:
            continue

        price = _menu_item_price(item)

        if price is None:
            continue

        if not _matches_dietary_preference(
            item,
            dietary_preference,
        ):
            continue

        score, reasons = _score_item(
            item,
            cuisine_preference=cuisine_preference,
            spice_level=spice_level,
            dietary_preference=dietary_preference,
            meal_preference=meal_preference,
            history_counts=history_counts,
        )

        recommendations.append(
            {
                "item_id": item.get("id"),
                "title": title,
                "current_price": price,
                "score": score,
                "reasons": reasons,
            }
        )

    recommendations.sort(
        key=lambda recommendation: (
            -recommendation["score"],
            recommendation["title"].lower(),
        )
    )

    return {
        "recommendations": recommendations[: max(1, limit)],
        "preferences_used": bool(preferences),
        "orders_analyzed": len(orders),
    }
