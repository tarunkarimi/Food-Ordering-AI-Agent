"""Advanced recommendation constraints and ranking."""

import re
from typing import Any


def _normalize(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def memory_preference_signal(
    item: dict[str, Any],
    memories: list[Any] | None,
) -> tuple[bool, int, list[str]]:
    """Return whether remembered preferences exclude or favor a menu item.

    Conversational memory is matched as a whole phrase in current menu text.
    This keeps generic dislikes from accidentally matching partial words.
    """
    if not memories:
        return False, 0, []

    text = _text(item)
    ingredients = item.get("ingredients")
    ingredient_values = _ingredient_values(ingredients)
    complete_ingredients = (
        item.get("ingredients_complete") is True
        and bool(ingredient_values)
    )
    positive_matches = 0

    for memory in memories:
        if isinstance(memory, dict):
            value = memory.get("memory_value")
            polarity = memory.get("polarity")
        else:
            value = getattr(memory, "memory_value", None)
            polarity = getattr(memory, "polarity", None)

        phrase = _normalize(value)
        if not phrase:
            continue

        variants = [phrase]
        if phrase.endswith(" food"):
            variants.append(phrase[:-5].strip())

        matches = any(
            _contains_phrase(variant, text)
            or any(_contains_phrase(variant, ingredient) for ingredient in ingredient_values)
            for variant in variants
            if variant
        )
        if not matches:
            if polarity == "dislike" and not complete_ingredients:
                # Menu text is not a complete ingredient declaration. When
                # the menu cannot establish safety, honor the explicit
                # restriction conservatively instead of assuming a match is
                # absent because it was omitted from the description.
                return True, 0, []
            continue

        if polarity == "dislike":
            return True, 0, []
        if polarity == "like":
            positive_matches += 1

    if not positive_matches:
        return False, 0, []

    return False, min(positive_matches, 2) * 6, ["matches a food you like"]


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
        item.get("ingredients"),
    ]

    return " ".join(
        str(value)
        for value in values
        if value is not None
    ).lower()


def _ingredient_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [part.strip().lower() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip().lower() for part in value if str(part).strip()]
    return []


def _contains_phrase(phrase: str, text: str) -> bool:
    if not phrase or not text:
        return False
    escaped_phrase = r"\s+".join(re.escape(part) for part in phrase.split())
    return bool(re.search(rf"(?<!\w){escaped_phrase}(?!\w)", text))


_PLANT_MILK_SOURCES = (
    "almond", "cashew", "coconut", "hemp", "hazelnut", "macadamia",
    "oat", "pea", "rice", "soy", "soya",
)


def _is_safe_animal_term_use(
    phrase: str,
    text: str,
    match: re.Match[str],
) -> bool:
    """Recognize common negated or plant-based uses of animal terms."""
    prefix = text[max(0, match.start() - 48):match.start()]
    suffix = text[match.end():match.end() + 16]

    if re.search(
        r"(?:\bno|\bwithout|\bfree\s+(?:of|from)|\bnon|"
        r"\bdoes\s+not\s+contain|\bdoesn't\s+contain)[\s-]*$",
        prefix,
    ):
        return True
    if re.match(r"^\s*[- ]free\b", suffix):
        return True

    if phrase in {"milk", "dairy", "meat"}:
        source_pattern = "|".join(
            re.escape(source) for source in _PLANT_MILK_SOURCES
        )
        if re.search(rf"\b(?:{source_pattern})\s+$", prefix):
            return True
        if re.search(r"\b(?:plant(?:[- ]based)?|vegan)\s+$", prefix):
            return True

    return False


def _contains_animal_derived_ingredient(text: str) -> bool:
    for phrase in _VEGAN_FORBIDDEN:
        escaped_phrase = r"\s+".join(re.escape(part) for part in phrase.split())
        for match in re.finditer(rf"(?<!\w){escaped_phrase}(?!\w)", text):
            if not _is_safe_animal_term_use(phrase, text, match):
                return True
    return False


def _dietary_labels(item: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for field in ("dietary", "dietary_labels", "dietary_tags"):
        value = item.get(field)
        values = value if isinstance(value, list) else [value]
        for label in values:
            if isinstance(label, str):
                labels.update(part.strip().lower() for part in re.split(r"[,;]", label) if part.strip())
    return labels


_VEGAN_FORBIDDEN = (
    # Meat and poultry.
    "meat", "chicken", "turkey", "duck", "beef", "pork", "lamb",
    "mutton", "veal", "goat", "venison", "bison", "rabbit", "poultry",
    "lard", "tallow", "suet", "animal fat", "bone broth",
    # Fish and seafood, including common sauces and extracts.
    "fish", "fish sauce", "anchovy", "bonito", "dashi", "prawn", "shrimp",
    "shrimp paste", "crab", "lobster", "seafood", "shellfish", "oyster",
    "oyster sauce", "mussel", "clam", "scallop", "squid", "octopus",
    # Dairy and common milk derivatives.
    "milk", "dairy", "milk powder", "milk solids", "milk protein", "milk fat",
    "cream", "cheese", "butter", "butterfat", "buttermilk", "yogurt",
    "yoghurt", "curd", "ghee", "paneer", "whey", "whey powder",
    "whey protein", "casein", "caseinate", "caseinates", "lactose",
    "lactalbumin", "lactoglobulin",
    # Eggs and common egg derivatives; gelatin/collagen and honey.
    "egg", "eggs", "egg white", "egg yolk", "albumin", "albumen",
    "ovalbumin", "lysozyme", "gelatin", "gelatine", "collagen", "honey",
    "beeswax", "propolis", "royal jelly", "rennet", "isinglass", "carmine",
    "cochineal", "shellac",
)

_VEGAN_CONTRARY_LABELS = (
    "non vegetarian", "nonvegetarian", "non veg", "nonveg", "non vegan",
    "nonvegan", "not vegan", "not vegetarian", "omnivore", "animal based",
    "contains animal products", "contains meat", "meat eater",
)


def matches_dietary_preference(
    item: dict[str, Any],
    dietary_preference: str | None,
) -> bool:
    """Apply known dietary exclusions and require evidence for vegan items.

    The current menu service does not define ingredient fields. A menu item
    can opt into known-safe ingredient matching with ``ingredients`` plus
    ``ingredients_complete=True``, or provide an explicit vegan dietary label.
    """
    preference = _normalize(dietary_preference)
    if not preference:
        return True

    labels = _dietary_labels(item)
    text = _text(item)
    ingredients = _ingredient_values(item.get("ingredients"))
    evidence = " ".join((text, *ingredients))

    if "vegan" in preference:
        normalized_labels = {
            re.sub(r"[-_]+", " ", label).strip()
            for label in labels
        }
        if any(
            _contains_phrase(contrary_label, label)
            for contrary_label in _VEGAN_CONTRARY_LABELS
            for label in normalized_labels
        ):
            return False
        if _contains_animal_derived_ingredient(evidence):
            return False
        if "vegan" in labels:
            return True
        return bool(item.get("ingredients_complete") is True and ingredients)

    if "vegetarian" in preference or preference in {"veg", "vegetarian"}:
        forbidden = (
            "chicken", "mutton", "lamb", "fish", "prawn", "shrimp",
            "seafood", "egg", "beef", "pork", "turkey", "duck",
        )
        if any(_contains_phrase(term, evidence) for term in forbidden):
            return False
        if "non-vegetarian" in labels or "non vegetarian" in labels:
            return False
    return True


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
    return matches_dietary_preference(item, dietary_preference)


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
    ai_memories: list[Any] | None = None,
) -> tuple[int, list[str]]:
    text = _text(item)
    title = _normalize(item.get("title"))

    score = 0
    reasons: list[str] = []

    _, memory_score, memory_reasons = memory_preference_signal(
        item,
        ai_memories,
    )
    score += memory_score
    reasons.extend(memory_reasons)

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
    ai_memories: list[Any] | None = None,
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

        memory_disliked, _, _ = memory_preference_signal(
            item,
            ai_memories,
        )
        if memory_disliked:
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
            ai_memories=ai_memories,
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
