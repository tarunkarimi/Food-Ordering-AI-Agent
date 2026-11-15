from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.db.models.user import User
from src.db.models.ai_memory import UserAIMemory

logger = logging.getLogger(__name__)

_MAX_MEMORIES = 50
_MAX_CONTEXT_MEMORIES = 20
_MAX_MESSAGE_LENGTH = 4000


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

# Generic explicit positive preference.
_POSITIVE_PATTERN = re.compile(
    r"\b(?:i\s+)?(?:(?:really|really\s+really)\s+)?"
    r"(?:like|love|prefer|enjoy)\s+"
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


def _normalize_timestamp(value: datetime | None) -> datetime:
    if not isinstance(value, datetime):
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _memory_field(memory, name: str):
    if isinstance(memory, dict):
        return memory.get(name)
    return getattr(memory, name, None)


def _spice_food_value(memory) -> str | None:
    memory_type = _memory_field(memory, "memory_type")
    value = _normalize_value(str(_memory_field(memory, "memory_value") or ""))
    if memory_type == "spice_level":
        return value
    if memory_type == "preference" and value.endswith(" food"):
        return value[:-5].strip()
    return None


def _memories_conflict(left, right) -> bool:
    left_type = _memory_field(left, "memory_type")
    right_type = _memory_field(right, "memory_type")
    left_key = _memory_field(left, "memory_key")
    right_key = _memory_field(right, "memory_key")
    left_value = _normalize_value(str(_memory_field(left, "memory_value") or ""))
    right_value = _normalize_value(str(_memory_field(right, "memory_value") or ""))
    left_polarity = _memory_field(left, "polarity")
    right_polarity = _memory_field(right, "polarity")

    if left_type == right_type and left_key == right_key:
        if left_value == right_value and left_polarity != right_polarity:
            return True
        if (
            left_type in {"spice_level", "dietary"}
            and left_value != right_value
        ):
            return True

    left_spice = _spice_food_value(left)
    right_spice = _spice_food_value(right)
    return bool(
        left_polarity != right_polarity
        and left_spice
        and left_spice == right_spice
    )


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
    if (
        not isinstance(user_message, str)
        or not user_message.strip()
        or len(user_message) > _MAX_MESSAGE_LENGTH
    ):
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
    user_id: int,
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
    user_id: int,
    memories: list[dict],
    *,
    occurred_at: datetime | None = None,
) -> list[UserAIMemory]:
    """Persist explicit memories, serializing updates for each user."""
    if not user_id or not memories:
        return []

    # A per-user row lock makes opposite-preference resolution deterministic
    # when two chat requests for the same user arrive concurrently.
    locked_user_id = db.scalar(
        select(User.id).where(User.id == user_id).with_for_update()
    )
    if locked_user_id is None:
        return []

    event_time = _normalize_timestamp(occurred_at)

    for memory_index, memory in enumerate(memories):
        if not isinstance(memory, dict):
            continue
        memory_type = str(memory.get("memory_type", ""))[:32]
        memory_key = str(memory.get("memory_key", ""))[:128]
        memory_value = _normalize_value(str(memory.get("memory_value", "")))[:255]
        polarity = str(memory.get("polarity", ""))
        if (
            not memory_type
            or not memory_key
            or not memory_value
            or polarity not in {"like", "dislike"}
        ):
            continue
        try:
            confidence = float(memory.get("confidence", 0.90))
        except (TypeError, ValueError):
            confidence = 0.90
        if not math.isfinite(confidence):
            confidence = 0.90
        confidence = min(max(confidence, 0.0), 1.0)
        # Keep the original message ordering if it expresses a conflict in
        # multiple clauses at the same API receipt timestamp.
        now = event_time + timedelta(microseconds=memory_index)

        values = {
            "user_id": user_id,
            "memory_type": memory_type,
            "memory_key": memory_key,
            "memory_value": memory_value,
            "polarity": polarity,
            "confidence": confidence,
            "mention_count": 1,
            "is_active": True,
            "first_seen_at": now,
            "last_seen_at": now,
        }

        # Single-valued settings and exact/opposite preference pairs are
        # resolved against active rows while the per-user lock is held.
        active_memories = db.scalars(
            select(UserAIMemory).where(
                UserAIMemory.user_id == user_id,
                UserAIMemory.is_active.is_(True),
            )
        ).all()
        conflicting_ids = [
            existing.id
            for existing in active_memories
            if _memories_conflict(existing, values)
        ]
        # The user-row lock serializes writes; the source message timestamp
        # decides which preference wins if delayed graph work finishes later.
        if any(
            _normalize_timestamp(existing.last_seen_at) >= now
            for existing in active_memories
            if existing.id in conflicting_ids
        ):
            continue
        if conflicting_ids:
            db.execute(
                update(UserAIMemory)
                .where(
                    UserAIMemory.user_id == user_id,
                    UserAIMemory.id.in_(conflicting_ids),
                    UserAIMemory.is_active.is_(True),
                )
                .values(is_active=False)
            )

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
                "mention_count": case(
                    (
                        stmt.excluded.last_seen_at
                        > UserAIMemory.last_seen_at,
                        UserAIMemory.mention_count + 1,
                    ),
                    else_=UserAIMemory.mention_count,
                ),
                "confidence": func.greatest(
                    UserAIMemory.confidence,
                    stmt.excluded.confidence,
                ),
                "is_active": True,
                "last_seen_at": func.greatest(
                    UserAIMemory.last_seen_at,
                    stmt.excluded.last_seen_at,
                ),
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
    user_id: int,
    user_message: str,
    occurred_at: datetime | None = None,
) -> list[UserAIMemory]:
    memories = extract_memories(user_message)

    if not memories:
        return []

    return record_memories(
        db,
        user_id=user_id,
        memories=memories,
        occurred_at=occurred_at,
    )


# ---------------------------------------------------------------------------
# Retrieval / AI context
# ---------------------------------------------------------------------------

def list_user_memories(
    db: Session,
    *,
    user_id: int,
    limit: int = _MAX_MEMORIES,
) -> list[UserAIMemory]:
    safe_limit = max(1, min(limit, _MAX_MEMORIES))

    memories = db.execute(
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

    resolved = []
    for memory in memories:
        if any(_memories_conflict(existing, memory) for existing in resolved):
            continue
        resolved.append(memory)
    return resolved


def build_ai_memory_context(
    db: Session,
    user_id: int | None,
) -> dict:
    """Build a bounded, model-safe representation of explicit user memory."""
    base_context = {
        "memory_version": 1,
        "explicit_preferences": [],
    }

    if not user_id:
        return base_context

    memories = list_user_memories(
        db,
        user_id=user_id,
        limit=_MAX_MEMORIES,
    )[:_MAX_CONTEXT_MEMORIES]

    base_context["explicit_preferences"] = [
        {
            "memory_type": str(memory.memory_type)[:32],
            "memory_key": str(memory.memory_key)[:128],
            "memory_value": re.sub(
                r"[\x00-\x1f\x7f]",
                " ",
                str(memory.memory_value),
            )[:255],
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
    user_id: int,
) -> int:
    result = db.execute(
        delete(UserAIMemory).where(
            UserAIMemory.user_id == user_id
        )
    )

    return result.rowcount or 0
