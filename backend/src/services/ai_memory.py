from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.db.models.ai_memory import UserAIMemory

logger = logging.getLogger(__name__)

_MAX_MEMORIES = 50
_MAX_CONTEXT_MEMORIES = 20


# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------

# Explicit negative preference.
_NEGATIVE_PATTERN = re.compile(
    r"\b(?:i\s+don't\s+like|i\s+do\s+not\s+like|i\s+hate|i\s+dislike|"
    r"i\s+avoid|i\s+can't\s+stand|i\s+cannot\s+stand)\s+"
    r"(?P<value>[a-zA-Z][a-zA-Z0-9 '&-]{1,80}?)"
    r"(?=\s+(?:and|but)\s+|[.!?,;]|$)",
    re.IGNORECASE,
)

# Specific positive cuisine preference.
_CUISINE_PATTERN = re.compile(
    r"\b(?:(?:i\s+)?(?:(?:really|really\s+really)\s+)?(?:like|love|prefer|enjoy))\s+"
    r"(?P<value>(?:andhra|south indian|north indian|indian|chinese|italian|mexican|thai|korean|japanese|continental|mughlai|punjabi|bengali|tamil|telugu|kerala|hyderabadi)(?:\s+food|\s+cuisine))\b",
    re.I,
)

_DIETARY_PATTERN = re.compile(
    r"\b(?:(?:i\s+)?(?:really\s+)?(?:prefer|follow)|(?:i\s+)?(?:am|['?]m))\s+"
    r"(?P<value>vegetarian|vegan|pescatarian|non-vegetarian|non vegetarian)\b",
    re.I,
)

_SPICE_PATTERN = re.compile(
    r"\b(?:(?:i\s+)?(?:(?:really|really\s+really)\s+)?(?:prefer|like|love|enjoy))\s+"
    r"(?P<value>very spicy|mild|medium|spicy|hot)\s+food\b",
    re.I,
)

_MEAL_PATTERN = re.compile(
    r"\b(?:(?:i\s+)?(?:(?:really|really\s+really)\s+)?(?:prefer|like|love|enjoy))\s+"
    r"(?P<value>breakfast|lunch|dinner|brunch|snacks?)\b",
    re.I,
)




def _normalize_value(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip().lower())
    return value.strip(" .,;!?")


def _overlaps(
    start: int,
    end: int,
    spans: list[tuple[int, int]],
) -> bool:
    return any(
        start < other_end and end > other_start
        for other_start, other_end in spans
    )


def _build_memory(
    *,
    memory_type: str,
    memory_key: str,
    value: str,
    polarity: str,
    confidence: float,
) -> dict:
    return {
        "memory_type": memory_type,
        "memory_key": memory_key,
        "memory_value": _normalize_value(value),
        "polarity": polarity,
        "confidence": confidence,
    }


def extract_memories(user_message: str) -> list[dict]:
    """Extract conservative explicit food preferences from one message."""
    if not user_message or not user_message.strip():
        return []

    memories: list[dict] = []

    # Split coordinated preferences into independent clauses.
    # Example:
    #   "I really like Andhra food and prefer spicy food."
    # becomes:
    #   "I really like Andhra food"
    #   "prefer spicy food"
    clauses = re.split(
        r"\s+(?:and|but)\s+",
        user_message.strip(),
        flags=re.IGNORECASE,
    )

    for clause in clauses:
        clause = clause.strip(" .,!;?")

        if not clause:
            continue

        # ---------------------------------------------------------------
        # Negative preferences have highest priority.
        # ---------------------------------------------------------------
        negative_matches = list(
            _NEGATIVE_PATTERN.finditer(clause)
        )

        for match in negative_matches:
            value = _normalize_value(match.group("value"))

            if not value:
                continue

            memories.append(
                _build_memory(
                    memory_type="preference",
                    memory_key="preference",
                    value=value,
                    polarity="dislike",
                    confidence=0.95,
                )
            )

        if negative_matches:
            # Do not allow positive patterns to reinterpret the same
            # negative clause.
            continue

        # ---------------------------------------------------------------
        # Structured positive preferences.
        # ---------------------------------------------------------------
        specialized_patterns = (
            ("spice_level", _SPICE_PATTERN),
            ("cuisine", _CUISINE_PATTERN),
            ("dietary", _DIETARY_PATTERN),
            ("meal", _MEAL_PATTERN),
        )

        matched_specialized = False

        for memory_type, pattern in specialized_patterns:
            for match in pattern.finditer(clause):
                value = _normalize_value(match.group("value"))

                if not value:
                    continue

                memories.append(
                    _build_memory(
                        memory_type=memory_type,
                        memory_key=memory_type,
                        value=value,
                        polarity="like",
                        confidence=0.95,
                    )
                )

                matched_specialized = True

        # ---------------------------------------------------------------
        # Generic positive preference.
        # ---------------------------------------------------------------
        if not matched_specialized:
            for match in _POSITIVE_PATTERN.finditer(clause):
                value = _normalize_value(match.group("value"))

                if not value:
                    continue

                memories.append(
                    _build_memory(
                        memory_type="preference",
                        memory_key="preference",
                        value=value,
                        polarity="like",
                        confidence=0.90,
                    )
                )

    # ---------------------------------------------------------------
    # Stable de-duplication.
    # ---------------------------------------------------------------
    unique: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    for memory in memories:
        identity = (
            memory["memory_type"],
            memory["memory_key"],
            memory["memory_value"],
            memory["polarity"],
        )

        if identity in seen:
            continue

        seen.add(identity)
        unique.append(memory)

    return unique

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _find_memory(
    db: Session,
    *,
    user_id: str,
    memory: dict,
) -> UserAIMemory | None:
    return db.execute(
        select(UserAIMemory).where(
            UserAIMemory.user_id == user_id,
            UserAIMemory.memory_type == memory["memory_type"],
            UserAIMemory.memory_key == memory["memory_key"],
            UserAIMemory.memory_value == memory["memory_value"],
            UserAIMemory.polarity == memory["polarity"],
        )
    ).scalar_one_or_none()


def record_memories(
    db: Session,
    user_id: str,
    memories: list[dict],
) -> list[UserAIMemory]:
    """Persist explicit memories with concurrency-safe PostgreSQL upserts."""
    if not user_id or not memories:
        return []

    now = datetime.now(timezone.utc)

    for memory in memories:
        values = {
            "user_id": user_id,
            "memory_type": memory["memory_type"],
            "memory_key": memory["memory_key"],
            "memory_value": memory["memory_value"],
            "polarity": memory["polarity"],
            "confidence": memory.get("confidence", 0.90),
            "mention_count": 1,
            "is_active": True,
            "first_seen_at": now,
            "last_seen_at": now,
        }

        stmt = pg_insert(UserAIMemory).values(**values)

        stmt = stmt.on_conflict_do_update(
            index_elements=[
                UserAIMemory.user_id,
                UserAIMemory.memory_type,
                UserAIMemory.memory_key,
                UserAIMemory.memory_value,
                UserAIMemory.polarity,
            ],
            set_={
                "mention_count": UserAIMemory.mention_count + 1,
                "confidence": func.greatest(
                    UserAIMemory.confidence,
                    stmt.excluded.confidence,
                ),
                "is_active": True,
                "last_seen_at": now,
            },
        )

        db.execute(stmt)

    db.flush()

    # Keep only the most recently observed active memories per user.
    active_ids = list(
        db.scalars(
            select(UserAIMemory.id)
            .where(
                UserAIMemory.user_id == user_id,
                UserAIMemory.is_active.is_(True),
            )
            .order_by(
                UserAIMemory.last_seen_at.desc(),
                UserAIMemory.id.desc(),
            )
            .limit(_MAX_MEMORIES)
        )
    )

    if active_ids:
        db.execute(
            delete(UserAIMemory).where(
                UserAIMemory.user_id == user_id,
                UserAIMemory.is_active.is_(True),
                UserAIMemory.id.not_in(active_ids),
            )
        )

    db.flush()

    return list(
        db.scalars(
            select(UserAIMemory)
            .where(
                UserAIMemory.user_id == user_id,
                UserAIMemory.is_active.is_(True),
            )
            .order_by(
                UserAIMemory.last_seen_at.desc(),
                UserAIMemory.id.desc(),
            )
        )
    )


def capture_user_message_memories(
    db: Session,
    *,
    user_id: str,
    user_message: str,
) -> list[UserAIMemory]:
    memories = extract_memories(user_message)

    if not memories:
        return []

    return record_memories(
        db,
        user_id=user_id,
        memories=memories,
    )


# ---------------------------------------------------------------------------
# Retrieval / AI context
# ---------------------------------------------------------------------------

def list_user_memories(
    db: Session,
    *,
    user_id: str,
    limit: int = _MAX_MEMORIES,
) -> list[UserAIMemory]:
    safe_limit = max(1, min(limit, _MAX_MEMORIES))

    return db.execute(
        select(UserAIMemory)
        .where(
            UserAIMemory.user_id == user_id,
            UserAIMemory.is_active.is_(True),
        )
        .order_by(
            UserAIMemory.last_seen_at.desc(),
            UserAIMemory.id.desc(),
        )
        .limit(safe_limit)
    ).scalars().all()


def build_ai_memory_context(
    db: Session,
    user_id: str | None,
) -> dict:
    """Build a bounded, model-safe representation of explicit user memory."""
    base_context = {
        "memory_version": 1,
        "explicit_preferences": [],
    }

    if not user_id:
        return base_context

    memories = list(
        db.scalars(
            select(UserAIMemory)
            .where(
                UserAIMemory.user_id == user_id,
                UserAIMemory.is_active.is_(True),
            )
            .order_by(
                UserAIMemory.last_seen_at.desc(),
                UserAIMemory.id.desc(),
            )
            .limit(_MAX_CONTEXT_MEMORIES)
        )
    )

    base_context["explicit_preferences"] = [
        {
            "memory_type": memory.memory_type,
            "memory_key": memory.memory_key,
            "memory_value": memory.memory_value,
            "polarity": memory.polarity,
            "confidence": float(memory.confidence),
            "mention_count": memory.mention_count,
        }
        for memory in memories
    ]

    return base_context

def delete_user_memory(
    db: Session,
    *,
    user_id: int,
    memory_id: int,
) -> bool:
    memory = (
        db.query(UserAIMemory)
        .filter(
            UserAIMemory.id == memory_id,
            UserAIMemory.user_id == user_id,
            UserAIMemory.is_active.is_(True),
        )
        .first()
    )

    if memory is None:
        return False

    memory.is_active = False
    db.flush()

    return True

def clear_user_memories(
    db: Session,
    *,
    user_id: str,
) -> int:
    result = db.execute(
        delete(UserAIMemory).where(
            UserAIMemory.user_id == user_id
        )
    )

    return result.rowcount or 0




