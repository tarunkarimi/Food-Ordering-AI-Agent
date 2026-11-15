import pytest

from src.services.persistent_ordering_intelligence import (
    build_persistent_ai_ordering_context,
    record_order_intelligence,
)

def test_legacy_aggregate_writer_is_disabled_without_database_access():
    with pytest.raises(RuntimeError, match="not tenant-scoped"):
        record_order_intelligence(object(), user_id=41, order=object())


def test_empty_profile_has_empty_ai_context():
    class EmptyResult:
        def all(self):
            return []

    class QueryOnlySession:
        def scalars(self, statement):
            return EmptyResult()

    context = build_persistent_ai_ordering_context(
        QueryOnlySession(),
        user_id=41,
    )

    assert context["ordering_history"]["total_orders"] == 0
    assert context["favorite_items"] == []
    assert context["favorite_restaurants"] == []
    assert context["weekday_patterns"] == {}
    assert context["meal_period_patterns"] == {}
