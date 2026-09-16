"""Advanced recommendation constraints and ranking."""

from typing import Any


def _normalize(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _text(item: dict[str, Any]) -> str:
    values = [
        item.get("title"),
        item.get("description"),
        item.get("category"),
        item.get("cuisine"),
        item.get("dietary"),
        item.get("tags"),
        item.get("spice_level"),
        item.get("meal"),
        item.get("meal_type"),
    ]

    return " ".join(
        str(value)
        for value in values
        if value is not None
    ).lower()


def _price(item: dict[str, Any]) -> float | None:
    try:
        value = float(item.get("base_price"))
    except (TypeError, ValueError):
        return None

    if value < 0:
        return None

    return value


def _matches_budget(
    item: dict[str, Any],
    max_price: float | None,
) -> bool:
    if max_price is None:
        return True

    price = _price(item)

    return price is not None and price <= max_price


def _matches_dietary(
    item: dict[str, Any],
    dietary_preference: str | None,
) -> bool:
    preference = _normalize(dietary_preference)

    if not preference:
        return True

    text = _text(item)

    if preference in {"veg", "vegetarian"} or "vegetarian" in preference:
        forbidden = (
            "chicken",
            "mutton",
            "lamb",
            "fish",
            "prawn",
            "prawns",
            "seafood",
            "egg",
            "beef",
            "pork",
        )

        if any(token in text for token in forbidden):
            return False

    return True


def _matches_meal(
    item: dict[str, Any],
    meal_preference: str | None,
) -> bool:
    meal = _normalize(meal_preference)

    if not meal:
        return True

    text = _text(item)

    return meal in text


def _persistent_item_signal(
    item: dict[str, Any],
    persistent_context: dict[str, Any] | None,
    current_restaurant: str | None,
) -> tuple[int, list[str]]:
    """Score lifetime ordering affinity from persistent intelligence."""

    if not persistent_context:
        return 0, []

    title = _normalize(item.get("title"))
    item_id = _normalize(item.get("id"))

    favorite_items = persistent_context.get("favorite_items", [])

    if not isinstance(favorite_items, list):
        favorite_items = []

    score = 0
    reasons: list[str] = []

    for favorite in favorite_items:
        if not isinstance(favorite, dict):
            continue

        favorite_title = _normalize(
            favorite.get("item_title")
            or favorite.get("title")
        )
        favorite_key = _normalize(
            favorite.get("item_key")
            or favorite.get("item_id")
        )

        matches = (
            bool(title and favorite_title and title == favorite_title)
            or bool(item_id and favorite_key and item_id == favorite_key)
        )

        if not matches:
            continue

        try:
            order_count = max(
                0,
                int(favorite.get("order_count", 0)),
            )
        except (TypeError, ValueError):
            order_count = 0

        try:
            total_quantity = max(
                0,
                int(favorite.get("total_quantity", 0)),
            )
        except (TypeError, ValueError):
            total_quantity = 0

        favorite_restaurant = _normalize(
            favorite.get("restaurant_name")
        )
        restaurant = _normalize(current_restaurant)

        # Lifetime repeat ordering is a strong signal.
        score += min(order_count * 2, 10)

        # Quantity provides an additional, smaller signal.
        score += min(total_quantity, 5)

        if restaurant and favorite_restaurant == restaurant:
            score += 5
            reasons.append("one of your frequently ordered items here")
        else:
            reasons.append("one of your frequently ordered items")

        return score, reasons

    return 0, []


def _persistent_restaurant_signal(
    persistent_context: dict[str, Any] | None,
    current_restaurant: str | None,
) -> tuple[int, list[str]]:
    """Score lifetime affinity for the current restaurant."""

    if not persistent_context or not current_restaurant:
        return 0, []

    restaurant_name = _normalize(current_restaurant)

    favorite_restaurants = persistent_context.get(
        "favorite_restaurants",
        [],
    )

    if not isinstance(favorite_restaurants, list):
        return 0, []

    for restaurant in favorite_restaurants:
        if not isinstance(restaurant, dict):
            continue

        name = _normalize(
            restaurant.get("restaurant_name")
        )

        if name != restaurant_name:
            continue

        try:
            order_count = max(
                0,
                int(restaurant.get("order_count", 0)),
            )
        except (TypeError, ValueError):
            order_count = 0

        if order_count <= 0:
            return 0, []

        return (
            min(order_count, 5),
            ["you frequently order from this restaurant"],
        )

    return 0, []


def _score(
    item: dict[str, Any],
    *,
    cuisine_preference: str | None,
    spice_level: str | None,
    meal_preference: str | None,
    history_counts: dict[str, int],
    persistent_context: dict[str, Any] | None = None,
    current_restaurant: str | None = None,
) -> tuple[int, list[str]]:
    text = _text(item)
    title = _normalize(item.get("title"))

    score = 0
    reasons: list[str] = []

    cuisine = _normalize(cuisine_preference)

    if cuisine and cuisine in text:
        score += 6
        reasons.append("matches your cuisine preference")

    spice = _normalize(spice_level)

    if spice and spice in text:
        score += 5
        reasons.append("matches your spice preference")

    meal = _normalize(meal_preference)

    if meal and meal in text:
        score += 4
        reasons.append("matches your meal preference")

    history_count = history_counts.get(title, 0)

    if history_count:
        score += min(history_count * 3, 9)
        reasons.append("similar to what you ordered before")

    persistent_item_score, persistent_item_reasons = (
        _persistent_item_signal(
            item,
            persistent_context,
            current_restaurant,
        )
    )

    score += persistent_item_score
    reasons.extend(persistent_item_reasons)

    restaurant_score, restaurant_reasons = (
        _persistent_restaurant_signal(
            persistent_context,
            current_restaurant,
        )
    )

    score += restaurant_score
    reasons.extend(restaurant_reasons)

    return score, reasons


def rank_recommendations(
    menu_items: list[dict[str, Any]],
    *,
    cuisine_preference: str | None = None,
    spice_level: str | None = None,
    dietary_preference: str | None = None,
    meal_preference: str | None = None,
    history_counts: dict[str, int] | None = None,
    persistent_context: dict[str, Any] | None = None,
    current_restaurant: str | None = None,
    max_price: float | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Rank only currently purchasable menu items.

    Persistent ordering intelligence can improve ranking, but current menu
    availability, price, and dietary constraints remain authoritative.
    """

    history_counts = history_counts or {}

    candidates: list[dict[str, Any]] = []

    for item in menu_items:
        if not isinstance(item, dict):
            continue

        title = str(item.get("title") or "").strip()

        if not title:
            continue

        price = _price(item)

        if price is None:
            continue

        if not _matches_budget(item, max_price):
            continue

        if not _matches_dietary(item, dietary_preference):
            continue

        if meal_preference and not _matches_meal(
            item,
            meal_preference,
        ):
            continue

        score, reasons = _score(
            item,
            cuisine_preference=cuisine_preference,
            spice_level=spice_level,
            meal_preference=meal_preference,
            history_counts=history_counts,
            persistent_context=persistent_context,
            current_restaurant=current_restaurant,
        )

        candidates.append(
            {
                "item_id": item.get("id"),
                "title": title,
                "current_price": price,
                "score": score,
                "reasons": reasons,
            }
        )

    candidates.sort(
        key=lambda entry: (
            -entry["score"],
            entry["current_price"],
            entry["title"].lower(),
        )
    )

    return candidates[: max(1, limit)]
