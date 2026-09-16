from datetime import datetime, timezone
import json

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models.order_history import OrderHistory
from src.db.models.ordering_intelligence import (
    UserOrderingItemStat,
    UserOrderingProfile,
    UserOrderingRestaurantStat,
)
from src.db.models.ordering_processed_order import UserOrderingProcessedOrder


def _load_json(value, default):
    if not value:
        return default.copy() if isinstance(default, dict) else list(default)

    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, type(default)) else default.copy()
    except (TypeError, ValueError, json.JSONDecodeError):
        return default.copy() if isinstance(default, dict) else list(default)


def _dump_json(value):
    return json.dumps(value, separators=(",", ":"))


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


def _get_or_create_profile(
    db: Session,
    user_id: int,
    lock: bool = False,
):
    profile_insert = (
        insert(UserOrderingProfile)
        .values(
            user_id=user_id,
            total_orders=0,
            total_items=0,
            total_spend=0,
            average_order_value=0,
            weekday_counts_json=_dump_json({}),
            meal_period_counts_json=_dump_json({}),
            updated_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(
            index_elements=[UserOrderingProfile.user_id],
        )
    )

    db.execute(profile_insert)

    query = select(UserOrderingProfile).where(
        UserOrderingProfile.user_id == user_id
    )

    if lock:
        query = query.with_for_update()

    return db.execute(query).scalar_one()


def record_order_intelligence(
    db: Session,
    user_id: int,
    order: OrderHistory,
) -> UserOrderingProfile:
    """Record one order into persistent ordering intelligence.

    Processing is idempotent per user/order. The profile row is locked while
    aggregation is performed so concurrent orders for the same user cannot
    overwrite each other's totals.
    """

    processed_insert = (
        insert(UserOrderingProcessedOrder)
        .values(
            user_id=user_id,
            order_id=order.order_id,
            processed_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(
            index_elements=[
                UserOrderingProcessedOrder.user_id,
                UserOrderingProcessedOrder.order_id,
            ],
        )
        .returning(UserOrderingProcessedOrder.id)
    )

    processed_id = db.execute(processed_insert).scalar_one_or_none()

    if processed_id is None:
        return _get_or_create_profile(db, user_id)

    profile = _get_or_create_profile(
        db,
        user_id,
        lock=True,
    )

    order_timestamp = order.created_at or datetime.now(timezone.utc)

    if order_timestamp.tzinfo is None:
        order_timestamp = order_timestamp.replace(tzinfo=timezone.utc)

    items = _load_items(order)
    total_items = sum(_quantity(item) for item in items)

    profile.total_orders = (profile.total_orders or 0) + 1
    profile.total_items = (profile.total_items or 0) + total_items
    profile.total_spend = (profile.total_spend or 0) + (order.subtotal or 0)

    profile.average_order_value = (
        profile.total_spend / profile.total_orders
        if profile.total_orders
        else 0
    )

    profile.last_order_id = order.order_id
    profile.last_order_at = order_timestamp
    profile.updated_at = datetime.now(timezone.utc)

    weekday_counts = _load_json(
        profile.weekday_counts_json,
        {},
    )

    weekday = order_timestamp.strftime("%A").lower()
    weekday_counts[weekday] = weekday_counts.get(weekday, 0) + 1
    profile.weekday_counts_json = _dump_json(weekday_counts)

    meal_period_counts = _load_json(
        profile.meal_period_counts_json,
        {},
    )

    meal_period = _meal_period(order_timestamp)
    meal_period_counts[meal_period] = (
        meal_period_counts.get(meal_period, 0) + 1
    )
    profile.meal_period_counts_json = _dump_json(meal_period_counts)

    restaurant = db.execute(
        select(UserOrderingRestaurantStat).where(
            UserOrderingRestaurantStat.user_id == user_id,
            UserOrderingRestaurantStat.restaurant_name
            == order.restaurant_name,
        )
    ).scalar_one_or_none()

    if restaurant is None:
        restaurant = UserOrderingRestaurantStat(
            user_id=user_id,
            restaurant_name=order.restaurant_name,
            order_count=0,
            total_spend=0,
        )
        db.add(restaurant)

    restaurant.order_count = (restaurant.order_count or 0) + 1
    restaurant.total_spend = (
        restaurant.total_spend or 0
    ) + (order.subtotal or 0)

    for item in items:
        item_key = _item_key(item)

        if not item_key:
            continue

        item_title = _item_title(item)
        quantity = _quantity(item)

        item_stat = db.execute(
            select(UserOrderingItemStat).where(
                UserOrderingItemStat.user_id == user_id,
                UserOrderingItemStat.item_key == item_key,
                UserOrderingItemStat.restaurant_name
                == order.restaurant_name,
            )
        ).scalar_one_or_none()

        if item_stat is None:
            item_stat = UserOrderingItemStat(
                user_id=user_id,
                item_key=item_key,
                item_title=item_title,
                restaurant_name=order.restaurant_name,
                order_count=0,
                total_quantity=0,
                last_ordered_at=order_timestamp,
            )
            db.add(item_stat)

        item_stat.item_title = item_title
        item_stat.order_count = (item_stat.order_count or 0) + 1
        item_stat.total_quantity = (
            item_stat.total_quantity or 0
        ) + quantity
        item_stat.last_ordered_at = order_timestamp

    db.flush()

    return profile


def get_persistent_ordering_profile(
    db: Session,
    user_id: int,
    restaurant_name: str | None = None,
):
    profile = _get_or_create_profile(db, user_id)

    item_query = select(UserOrderingItemStat).where(
        UserOrderingItemStat.user_id == user_id
    )

    if restaurant_name:
        item_query = item_query.where(
            UserOrderingItemStat.restaurant_name == restaurant_name
        )

    item_stats = db.execute(
        item_query.order_by(
            UserOrderingItemStat.order_count.desc(),
            UserOrderingItemStat.total_quantity.desc(),
            UserOrderingItemStat.last_ordered_at.desc(),
        )
    ).scalars().all()

    restaurant_stats = db.execute(
        select(UserOrderingRestaurantStat)
        .where(UserOrderingRestaurantStat.user_id == user_id)
        .order_by(
            UserOrderingRestaurantStat.order_count.desc(),
            UserOrderingRestaurantStat.total_spend.desc(),
        )
    ).scalars().all()

    weekday_patterns = _load_json(
        profile.weekday_counts_json,
        {},
    )

    meal_period_patterns = _load_json(
        profile.meal_period_counts_json,
        {},
    )

    favorite_items = [
        {
            "item_key": item.item_key,
            "item_title": item.item_title,
            "restaurant_name": item.restaurant_name,
            "order_count": item.order_count,
            "total_quantity": item.total_quantity,
            "last_ordered_at": item.last_ordered_at,
        }
        for item in item_stats[:10]
    ]

    favorite_restaurants = [
        {
            "restaurant_name": restaurant.restaurant_name,
            "order_count": restaurant.order_count,
            "total_spend": float(restaurant.total_spend or 0),
        }
        for restaurant in restaurant_stats[:10]
    ]

    return {
        "user_id": user_id,
        "total_orders": profile.total_orders or 0,
        "total_items": profile.total_items or 0,
        "total_spend": float(profile.total_spend or 0),
        "average_order_value": float(
            profile.average_order_value or 0
        ),
        "last_order_id": profile.last_order_id,
        "last_order_at": profile.last_order_at,
        "weekday_patterns": weekday_patterns,
        "meal_period_patterns": meal_period_patterns,
        "favorite_items": favorite_items,
        "favorite_restaurants": favorite_restaurants,
    }


def build_persistent_ai_ordering_context(
    db: Session,
    user_id: int,
    restaurant_name: str | None = None,
):
    profile = get_persistent_ordering_profile(
        db,
        user_id,
        restaurant_name=restaurant_name,
    )

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
