from datetime import datetime, timezone
from decimal import Decimal
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models.order_history import OrderHistory


def _load_json(value, default):
    if not value:
        return default.copy() if isinstance(default, dict) else list(default)

    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, type(default)) else default.copy()
    except (TypeError, ValueError, json.JSONDecodeError):
        return default.copy() if isinstance(default, dict) else list(default)


def _load_items(order: OrderHistory):
    return _load_json(order.items_json, [])


def _item_key(item):
    return str(
        item.get("item_id") or item.get("id") or item.get("title") or ""
    ).strip()


def _item_title(item):
    return str(
        item.get("title") or item.get("name") or _item_key(item)
    ).strip()


def _quantity(item):
    try:
        return max(1, int(item.get("quantity", 1)))
    except (TypeError, ValueError):
        return 1


def _meal_period(timestamp):
    hour = timestamp.hour

    if 5 <= hour < 11:
        return "breakfast"
    if 11 <= hour < 15:
        return "lunch"
    if 15 <= hour < 18:
        return "snacks"
    if 18 <= hour < 23:
        return "dinner"

    return "late_night"


def record_order_intelligence(
    db: Session,
    user_id: int,
    order: OrderHistory,
) -> None:
    """Reject writes to legacy aggregates that lack stable tenant keys.

    UserOrderingItemStat and UserOrderingRestaurantStat identify restaurants
    by display name only. Existing rows are retained but never read as
    tenant-specific data. Tenant-scoped profiles are computed from
    OrderHistory instead; writing new legacy rows is intentionally disabled
    until a tenant-aware schema is available.
    """
    raise RuntimeError(
        "Legacy ordering aggregates are disabled because they are not tenant-scoped."
    )


def get_persistent_ordering_profile(
    db: Session,
    user_id: int,
    restaurant_name: str | None = None,
    subdomain: str | None = None,
):
    """Return a tenant-scoped profile using source order rows.

    Legacy summary tables key restaurants by display name. They cannot safely
    answer tenant-specific profile requests when names are duplicated, so this
    endpoint resolves one unambiguous tenant and aggregates its order rows.
    """
    context = build_persistent_ai_ordering_context(
        db,
        user_id=user_id,
        restaurant_name=restaurant_name,
        subdomain=subdomain,
    )
    history = context["ordering_history"]
    return {"user_id": user_id, **history}


def build_persistent_ai_ordering_context(
    db: Session,
    user_id: int,
    restaurant_name: str | None = None,
    subdomain: str | None = None,
):
    """Build AI context from order rows scoped to one verified tenant.

    The legacy aggregate tables use restaurant display name as their tenant
    key. Recompute this context from OrderHistory, whose rows carry subdomain,
    so identically named restaurants cannot share item/order signals.
    """
    if subdomain is None:
        tenant = _resolve_unique_ordering_subdomain(
            db,
            user_id=user_id,
        ) or ""
    elif (
        not isinstance(subdomain, str)
        or not subdomain.strip()
        or subdomain != subdomain.strip()
    ):
        return _empty_ai_ordering_context()
    else:
        tenant = subdomain
    if not tenant:
        return _empty_ai_ordering_context()

    orders = _load_tenant_order_history(
        db,
        user_id=user_id,
        subdomain=tenant,
        restaurant_name=restaurant_name,
    )
    orders = [
        order for order in orders
        if str(getattr(order, "status", "")).strip().lower()
        not in {"cancelled", "canceled", "failed", "rejected"}
    ]
    profile = _aggregate_tenant_ordering_context(orders)

    return {
        "ordering_history": {
            "total_orders": profile["total_orders"],
            "total_items": profile["total_items"],
            "total_spend": profile["total_spend"],
            "average_order_value": profile["average_order_value"],
            "last_order_id": profile["last_order_id"],
            "last_order_at": profile["last_order_at"],
            "weekday_patterns": profile["weekday_patterns"],
            "meal_period_patterns": profile["meal_period_patterns"],
            "favorite_items": profile["favorite_items"],
            "favorite_restaurants": profile["favorite_restaurants"],
        },
        "weekday_patterns": profile["weekday_patterns"],
        "meal_period_patterns": profile["meal_period_patterns"],
        "favorite_items": profile["favorite_items"],
        "favorite_restaurants": profile["favorite_restaurants"],
    }


def _resolve_unique_ordering_subdomain(
    db: Session,
    *,
    user_id: int,
) -> str | None:
    values = db.scalars(
        select(OrderHistory.subdomain)
        .where(
            OrderHistory.user_id == user_id,
            OrderHistory.subdomain.is_not(None),
            OrderHistory.subdomain != "",
        )
        .distinct()
        .limit(2)
    ).all()
    if (
        len(values) != 1
        or not isinstance(values[0], str)
        or not values[0].strip()
        or values[0] != values[0].strip()
    ):
        return None
    return values[0]


def _load_tenant_order_history(
    db: Session,
    *,
    user_id: int,
    subdomain: str,
    restaurant_name: str | None,
) -> list[OrderHistory]:
    query = select(OrderHistory).where(
        OrderHistory.user_id == user_id,
        OrderHistory.subdomain == subdomain,
    )
    if restaurant_name and restaurant_name.strip():
        query = query.where(OrderHistory.restaurant_name == restaurant_name.strip())
    return list(
        db.scalars(
            query.order_by(
                OrderHistory.created_at.desc(),
                OrderHistory.id.desc(),
            )
        ).all()
    )


def _empty_ai_ordering_context() -> dict:
    empty = {
        "total_orders": 0,
        "total_items": 0,
        "total_spend": 0.0,
        "average_order_value": 0.0,
        "last_order_id": None,
        "last_order_at": None,
        "weekday_patterns": {},
        "meal_period_patterns": {},
        "favorite_items": [],
        "favorite_restaurants": [],
    }
    return {
        "ordering_history": dict(empty),
        "weekday_patterns": {},
        "meal_period_patterns": {},
        "favorite_items": [],
        "favorite_restaurants": [],
    }


def _aggregate_tenant_ordering_context(orders: list[OrderHistory]) -> dict:
    total_spend = Decimal("0")
    total_items = 0
    weekday_patterns: dict[str, int] = {}
    meal_period_patterns: dict[str, int] = {}
    item_stats: dict[str, dict] = {}
    restaurant_stats: dict[str, dict] = {}

    for order in orders:
        timestamp = order.created_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        items = _load_items(order)
        quantity_sum = sum(_quantity(item) for item in items)
        total_items += quantity_sum
        total_spend += Decimal(str(order.subtotal or 0))
        weekday = timestamp.strftime("%A").lower()
        weekday_patterns[weekday] = weekday_patterns.get(weekday, 0) + 1
        meal_period = _meal_period(timestamp)
        meal_period_patterns[meal_period] = meal_period_patterns.get(meal_period, 0) + 1

        restaurant_name = str(order.restaurant_name or "").strip()
        restaurant = restaurant_stats.setdefault(
            restaurant_name,
            {"restaurant_name": restaurant_name, "order_count": 0, "total_spend": Decimal("0")},
        )
        restaurant["order_count"] += 1
        restaurant["total_spend"] += Decimal(str(order.subtotal or 0))

        for item in items:
            key = _item_key(item)
            if not key:
                continue
            stat = item_stats.setdefault(
                key,
                {
                    "item_key": key,
                    "item_title": _item_title(item),
                    "restaurant_name": restaurant_name,
                    "order_count": 0,
                    "total_quantity": 0,
                    "last_ordered_at": timestamp,
                },
            )
            stat["item_title"] = _item_title(item)
            stat["order_count"] += 1
            stat["total_quantity"] += _quantity(item)
            if timestamp > stat["last_ordered_at"]:
                stat["last_ordered_at"] = timestamp

    latest = orders[0] if orders else None
    sorted_items = sorted(
        item_stats.values(),
        key=lambda item: (
            -item["order_count"], -item["total_quantity"],
            item["item_title"].casefold(),
        ),
    )[:10]
    favorites = sorted(
        restaurant_stats.values(),
        key=lambda item: (-item["order_count"], -item["total_spend"]),
    )[:10]
    for favorite in favorites:
        favorite["total_spend"] = float(favorite["total_spend"])

    return {
        "total_orders": len(orders),
        "total_items": total_items,
        "total_spend": float(total_spend),
        "average_order_value": float(total_spend / len(orders)) if orders else 0.0,
        "last_order_id": latest.order_id if latest else None,
        "last_order_at": latest.created_at if latest else None,
        "weekday_patterns": weekday_patterns,
        "meal_period_patterns": meal_period_patterns,
        "favorite_items": sorted_items,
        "favorite_restaurants": favorites,
    }
