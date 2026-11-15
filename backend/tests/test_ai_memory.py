import json

import pytest
from sqlalchemy import delete

from src.db.database import SessionLocal
from src.db.models import OrderHistory, User, UserAIMemory
from src.services.ai_memory import (
    build_ai_memory_context,
    capture_user_message_memories,
    extract_memories,
    list_user_memories,
)

from tests.test_authenticated_cart import signup_and_login


@pytest.fixture(autouse=True)
def prevent_otp_delivery(monkeypatch):
    monkeypatch.setattr(
        "src.api.routes.auth.deliver_verification_code",
        lambda **kwargs: None,
    )


@pytest.fixture(autouse=True)
def cleanup_synthetic_users(monkeypatch):
    """Delete only users created by this test through the shared helper."""
    created_user_ids = []
    original_signup = signup_and_login

    def tracked_signup():
        user_id, token = original_signup()
        created_user_ids.append(user_id)
        return user_id, token

    monkeypatch.setitem(globals(), "signup_and_login", tracked_signup)
    yield

    if created_user_ids:
        with SessionLocal() as db:
            db.execute(delete(User).where(User.id.in_(created_user_ids)))
            db.commit()


def test_extract_explicit_positive_preference():
    memories = extract_memories(
        "I really like Andhra food and prefer spicy food."
    )

    values = {
        (
            memory["memory_key"],
            memory["memory_value"],
            memory["polarity"],
        )
        for memory in memories
    }

    assert ("cuisine", "andhra food", "like") in values
    assert ("spice_level", "spicy", "like") in values


def test_extract_negative_preference():
    memories = extract_memories(
        "I don't like mushrooms."
    )

    assert memories
    assert memories[0]["polarity"] == "dislike"
    assert memories[0]["memory_value"] == "mushrooms"


def test_capture_memory_is_deduplicated_and_counted():
    user_id, _ = signup_and_login()

    from src.db.database import SessionLocal

    with SessionLocal() as db:
        capture_user_message_memories(
            db,
            user_id=user_id,
            user_message="I prefer spicy food.",
        )
        db.commit()

        capture_user_message_memories(
            db,
            user_id=user_id,
            user_message="I prefer spicy food.",
        )
        db.commit()

        memories = list_user_memories(
            db,
            user_id=user_id,
        )

        assert len(memories) == 1
        assert memories[0].mention_count == 2
        assert memories[0].is_active is True


def test_memory_is_user_scoped():
    user_a, _ = signup_and_login()
    user_b, _ = signup_and_login()

    from src.db.database import SessionLocal

    with SessionLocal() as db:
        capture_user_message_memories(
            db,
            user_id=user_a,
            user_message="I like Andhra food.",
        )
        db.commit()

        assert list_user_memories(
            db,
            user_id=user_a,
        )

        assert list_user_memories(
            db,
            user_id=user_b,
        ) == []


def test_ai_memory_context_is_bounded_and_model_safe():
    user_id, _ = signup_and_login()

    from src.db.database import SessionLocal

    with SessionLocal() as db:
        capture_user_message_memories(
            db,
            user_id=user_id,
            user_message="I prefer vegetarian food.",
        )
        db.commit()

        context = build_ai_memory_context(
            db,
            user_id=user_id,
        )

        assert context["memory_version"] == 1
        assert len(context["explicit_preferences"]) == 1
        assert "id" not in context["explicit_preferences"][0]
        assert "user_id" not in context["explicit_preferences"][0]


def test_empty_ai_memory_context():
    user_id, _ = signup_and_login()

    from src.db.database import SessionLocal

    with SessionLocal() as db:
        context = build_ai_memory_context(
            db,
            user_id=user_id,
        )

        assert context == {
            "memory_version": 1,
            "explicit_preferences": [],
        }

def test_negative_spicy_preference_does_not_create_positive_memory():
    memories = extract_memories("I don't like spicy food.")

    assert any(
        memory["memory_value"] == "spicy food"
        and memory["polarity"] == "dislike"
        for memory in memories
    )

    assert not any(
        memory["memory_value"] == "spicy"
        and memory["polarity"] == "positive"
        for memory in memories
    )


def test_negative_vegetarian_preference_does_not_create_positive_memory():
    memories = extract_memories("I hate vegetarian food.")

    assert any(
        memory["memory_value"] == "vegetarian food"
        and memory["polarity"] == "dislike"
        for memory in memories
    )

    assert not any(
        memory["memory_value"] == "vegetarian"
        and memory["polarity"] == "positive"
        for memory in memories
    )


