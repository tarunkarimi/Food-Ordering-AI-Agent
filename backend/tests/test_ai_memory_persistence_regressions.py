"""PostgreSQL regressions for authenticated conversational memory."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
from uuid import uuid4
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import delete, select

from src.agents.nodes import chatbot as chatbot_module
from src.agents.nodes.chatbot import chatbot
from src.db.database import SessionLocal
from src.db.models import User, UserAIMemory
from src.services.ai_memory import (
    build_ai_memory_context,
    capture_user_message_memories,
    list_user_memories,
)


@pytest.fixture
def create_test_user():
    """Create synthetic users and delete only those users after the test."""

    created_user_ids = []

    def create_user():
        user = User(
            email=f"ai-memory-regression-{uuid4().hex}@example.test",
            phone=None,
            password_hash="not-used-by-this-test",
            email_verified=True,
            phone_verified=False,
            is_active=True,
        )
        with SessionLocal() as db:
            db.add(user)
            db.commit()
            db.refresh(user)
            created_user_ids.append(user.id)
            return user.id

    yield create_user

    if created_user_ids:
        with SessionLocal() as db:
            db.execute(delete(User).where(User.id.in_(created_user_ids)))
            db.commit()


def test_memory_survives_fresh_session_resolves_conflicts_and_is_user_scoped(
    create_test_user,
):
    user_a_id = create_test_user()
    user_b_id = create_test_user()

    with SessionLocal() as db:
        capture_user_message_memories(
            db,
            user_id=user_a_id,
            user_message="I like spicy chicken.",
        )
        db.commit()

    # A distinct SQLAlchemy session models a later chat/session request.
    with SessionLocal() as db:
        remembered = list_user_memories(db, user_id=user_a_id)
        assert [(memory.memory_value, memory.polarity) for memory in remembered] == [
            ("spicy chicken", "like")
        ]

        capture_user_message_memories(
            db,
            user_id=user_a_id,
            user_message="I don't like spicy chicken.",
        )
        capture_user_message_memories(
            db,
            user_id=user_a_id,
            user_message="I don't like spicy chicken.",
        )
        db.commit()

    with SessionLocal() as db:
        active = list_user_memories(db, user_id=user_a_id)
        assert [(memory.memory_value, memory.polarity) for memory in active] == [
            ("spicy chicken", "dislike")
        ]
        assert active[0].mention_count == 2

        all_user_memories = db.scalars(
            select(UserAIMemory).where(UserAIMemory.user_id == user_a_id)
        ).all()
        assert len(all_user_memories) == 2
        assert sum(memory.is_active for memory in all_user_memories) == 1
        assert list_user_memories(db, user_id=user_b_id) == []
        assert build_ai_memory_context(db, user_id=user_b_id)[
            "explicit_preferences"
        ] == []


def test_persisted_memory_is_injected_into_a_later_chat_request(
    create_test_user,
    monkeypatch,
):
    user_id = create_test_user()
    with SessionLocal() as db:
        capture_user_message_memories(
            db,
            user_id=user_id,
            user_message="I really like Andhra food.",
        )
        db.commit()

    captured_messages = []
    model = Mock()
    model.invoke.side_effect = lambda messages: (
        captured_messages.extend(messages) or AIMessage(content="A fresh reply.")
    )
    monkeypatch.setattr(chatbot_module, "_model_with_tools", model)
    monkeypatch.setattr(
        chatbot_module,
        "_load_persistent_ordering_context",
        lambda state: {},
    )
    monkeypatch.setattr(chatbot_module, "_persist_cart", lambda state, cart: None)

    result = chatbot(
        {
            "messages": [HumanMessage(content="What should I order today?")],
            "cart": [],
            "restaurant_name": "Memory Regression Kitchen",
            "subdomain": "memory-regression",
            "user_id": user_id,
            "finished": False,
        }
    )

    assert result["messages"][-1].content == "A fresh reply."
    memory_contexts = [
        message[1]
        for message in captured_messages
        if isinstance(message, tuple)
        and len(message) == 2
        and message[0] == "system"
        and "EXPLICIT CUSTOMER MEMORY" in message[1]
    ]
    assert len(memory_contexts) == 1
    assert "andhra food" in memory_contexts[0].lower()


def test_newer_single_value_spice_preference_replaces_older_value(
    create_test_user,
):
    user_id = create_test_user()

    with SessionLocal() as db:
        capture_user_message_memories(
            db,
            user_id=user_id,
            user_message="I like spicy food.",
        )
        db.commit()

    with SessionLocal() as db:
        capture_user_message_memories(
            db,
            user_id=user_id,
            user_message="I prefer mild food.",
        )
        db.commit()

    with SessionLocal() as db:
        active = list_user_memories(db, user_id=user_id)
        assert [(memory.memory_type, memory.memory_value) for memory in active] == [
            ("spice_level", "mild")
        ]


def test_dislike_of_spicy_food_supersedes_earlier_spice_preference(
    create_test_user,
):
    user_id = create_test_user()

    with SessionLocal() as db:
        capture_user_message_memories(
            db,
            user_id=user_id,
            user_message="I like spicy food.",
        )
        db.commit()

    with SessionLocal() as db:
        capture_user_message_memories(
            db,
            user_id=user_id,
            user_message="I don't like spicy food.",
        )
        db.commit()

    with SessionLocal() as db:
        active = list_user_memories(db, user_id=user_id)
        assert [(memory.memory_type, memory.memory_value, memory.polarity) for memory in active] == [
            ("preference", "spicy food", "dislike")
        ]


def test_concurrent_memory_writes_remain_user_scoped_and_conflict_safe(
    create_test_user,
):
    user_a_id = create_test_user()
    user_b_id = create_test_user()
    writes = [
        (user_a_id, "I like spicy chicken."),
        (user_a_id, "I don't like spicy chicken."),
        (user_b_id, "I like Andhra food."),
    ]
    barrier = Barrier(len(writes))

    def write_memory(user_id: int, message: str) -> None:
        barrier.wait()
        with SessionLocal() as db:
            capture_user_message_memories(
                db,
                user_id=user_id,
                user_message=message,
            )
            db.commit()

    with ThreadPoolExecutor(max_workers=len(writes)) as executor:
        futures = [executor.submit(write_memory, *write) for write in writes]
        for future in futures:
            future.result()

    with SessionLocal() as db:
        user_a_memories = list_user_memories(db, user_id=user_a_id)
        user_b_memories = list_user_memories(db, user_id=user_b_id)

    assert len(user_a_memories) == 1
    assert user_a_memories[0].memory_value == "spicy chicken"
    assert user_a_memories[0].polarity in {"like", "dislike"}
    assert [(memory.memory_value, memory.polarity) for memory in user_b_memories] == [
        ("andhra food", "like")
    ]


def test_newer_original_message_wins_when_older_write_is_delayed(
    create_test_user,
):
    user_id = create_test_user()
    older_message_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    newer_message_at = older_message_at + timedelta(seconds=1)
    older_started = Event()
    newer_committed = Event()

    def write_older_message() -> None:
        older_started.set()
        assert newer_committed.wait(timeout=10)
        with SessionLocal() as db:
            capture_user_message_memories(
                db,
                user_id=user_id,
                user_message="I like paneer.",
                occurred_at=older_message_at,
            )
            db.commit()

    def write_newer_message() -> None:
        assert older_started.wait(timeout=10)
        with SessionLocal() as db:
            capture_user_message_memories(
                db,
                user_id=user_id,
                user_message="I don't like paneer.",
                occurred_at=newer_message_at,
            )
            db.commit()
        newer_committed.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        older_future = executor.submit(write_older_message)
        newer_future = executor.submit(write_newer_message)
        newer_future.result()
        older_future.result()

    with SessionLocal() as db:
        memories = list_user_memories(db, user_id=user_id)

    assert [(memory.memory_value, memory.polarity) for memory in memories] == [
        ("paneer", "dislike")
    ]


def test_replayed_message_timestamp_does_not_inflate_mention_count(
    create_test_user,
):
    user_id = create_test_user()
    message_at = datetime(2026, 2, 1, tzinfo=timezone.utc)

    for _ in range(2):
        with SessionLocal() as db:
            capture_user_message_memories(
                db,
                user_id=user_id,
                user_message="I like spicy chicken.",
                occurred_at=message_at,
            )
            db.commit()

    with SessionLocal() as db:
        memories = list_user_memories(db, user_id=user_id)

    assert len(memories) == 1
    assert memories[0].mention_count == 1
