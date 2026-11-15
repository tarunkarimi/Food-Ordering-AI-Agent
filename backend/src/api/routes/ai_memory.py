from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.dependencies import (
    AuthenticatedSession,
    get_current_session,
    get_db,
)
from src.db.database import SessionLocal
from src.services.ai_memory import (
    build_ai_memory_context,
    clear_user_memories,
    delete_user_memory,
    list_user_memories,
)

router = APIRouter()


def _serialize(memory) -> dict:
    return {
        "id": memory.id,
        "memory_type": memory.memory_type,
        "memory_key": memory.memory_key,
        "memory_value": memory.memory_value,
        "polarity": memory.polarity,
        "confidence": float(memory.confidence),
        "mention_count": memory.mention_count,
        "is_active": memory.is_active,
        "first_seen_at": memory.first_seen_at,
        "last_seen_at": memory.last_seen_at,
    }


@router.get("")
def get_ai_memories(
    current_session=Depends(get_current_session),
):
    """Return active explicit AI memories for the authenticated user."""
    with SessionLocal() as db:
        memories = list_user_memories(
            db,
            user_id=current_session.user.id,
        )

        return {
            "memories": [
                {
                    "id": memory.id,
                    "memory_type": memory.memory_type,
                    "memory_key": memory.memory_key,
                    "memory_value": memory.memory_value,
                    "polarity": memory.polarity,
                    "confidence": float(memory.confidence),
                    "mention_count": memory.mention_count,
                    "is_active": memory.is_active,
                    "first_seen_at": memory.first_seen_at,
                    "last_seen_at": memory.last_seen_at,
                }
                for memory in memories
                if memory.is_active
            ]
        }

@router.get("/ai-context")
def get_ai_memory_context(
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    return build_ai_memory_context(
        db,
        user_id=auth.user.id,
    )


@router.delete("/{memory_id}")
def remove_ai_memory(
    memory_id: int,
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    deleted = delete_user_memory(
        db,
        user_id=auth.user.id,
        memory_id=memory_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Memory not found.",
        )

    db.commit()

    return {
        "success": True,
        "memory_id": memory_id,
    }


@router.delete("")
def remove_all_ai_memories(
    auth: AuthenticatedSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    deleted_count = clear_user_memories(
        db,
        user_id=auth.user.id,
    )
    db.commit()

    return {
        "success": True,
        "deleted_count": deleted_count,
    }
