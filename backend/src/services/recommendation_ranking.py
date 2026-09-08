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


def _score(
    item: dict[str, Any],
    *,
    cuisine_preference: str | None,
    spice_level: str | None,
    meal_preference: str | None,
    history_counts: dict[str, int],
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

    return score, reasons


def rank_recommendations(
    menu_items: list[dict[str, Any]],
    *,
    cuisine_preference: str | None = None,
    spice_level: str | None = None,
    dietary_preference: str | None = None,
    meal_preference: str | None = None,
    history_counts: dict[str, int] | None = None,
    max_price: float | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Rank only currently purchasable menu items."""

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
