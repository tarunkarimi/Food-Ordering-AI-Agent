"""Database-independent conversational memory extraction tests."""

from types import SimpleNamespace

from src.services.ai_memory import (
    _memories_conflict,
    build_ai_memory_context,
    extract_memories,
)


def test_extracts_explicit_positive_food_preference():
    memories = extract_memories("I like spicy chicken.")

    assert memories == [
        {
            "memory_type": "preference",
            "memory_key": "preference",
            "memory_value": "spicy chicken",
            "polarity": "like",
            "confidence": 0.90,
        }
    ]


def test_extracts_explicit_dislike_without_positive_reinterpretation():
    memories = extract_memories("I don't like paneer.")

    assert len(memories) == 1
    assert memories[0]["memory_value"] == "paneer"
    assert memories[0]["polarity"] == "dislike"


def test_extracts_both_preferences_in_order_for_newer_conflict_resolution():
    memories = extract_memories(
        "I like spicy chicken but I don't like spicy chicken."
    )

    assert [memory["polarity"] for memory in memories] == ["like", "dislike"]
    assert {memory["memory_value"] for memory in memories} == {"spicy chicken"}


def test_repeated_preference_in_one_message_is_deduplicated():
    memories = extract_memories("I like chicken and I like chicken.")

    assert len(memories) == 1
    assert memories[0]["memory_value"] == "chicken"


def test_cross_category_spice_preference_conflicts_are_detected():
    assert _memories_conflict(
        {
            "memory_type": "spice_level",
            "memory_key": "spice_level",
            "memory_value": "spicy",
            "polarity": "like",
        },
        {
            "memory_type": "preference",
            "memory_key": "preference",
            "memory_value": "spicy food",
            "polarity": "dislike",
        },
    )


def test_empty_ambiguous_unrelated_and_malformed_input_create_no_memory():
    assert extract_memories("") == []
    assert extract_memories("   ") == []
    assert extract_memories(None) == []
    assert extract_memories("Maybe something tasty would be nice.") == []
    assert extract_memories("The restaurant is near my office.") == []
    assert extract_memories("I like " + ("chicken " * 1000)) == []


def test_memory_context_is_bounded_and_removes_control_characters():
    memories = [
        SimpleNamespace(
            memory_type="preference",
            memory_key="preference",
            memory_value="spicy\tchicken",
            polarity="like",
            confidence=0.9,
            mention_count=1,
        )
        for _ in range(25)
    ]

    class MemoryQuery:
        def execute(self, statement):
            assert statement._limit_clause.value == 50

            class Result:
                @staticmethod
                def scalars():
                    class ScalarResult:
                        @staticmethod
                        def all():
                            return memories[:50]

                    return ScalarResult()

            return Result()

    context = build_ai_memory_context(MemoryQuery(), user_id=17)

    assert len(context["explicit_preferences"]) == 20
    assert context["explicit_preferences"][0]["memory_value"] == "spicy chicken"
    assert "user_id" not in context["explicit_preferences"][0]
