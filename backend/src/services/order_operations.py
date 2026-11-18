"""Durable idempotency and retryable order-operation outbox helpers."""

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.db.models.order_operation import OrderOperation


class OperationConflict(ValueError):
    """An idempotency key was reused for different operation data."""


def get_order_operation(
    db: Session,
    *,
    user_id: int,
    idempotency_key: str,
) -> OrderOperation | None:
    return db.scalar(select(OrderOperation).where(
        OrderOperation.user_id == user_id,
        OrderOperation.idempotency_key == idempotency_key,
    ).with_for_update())


def fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def begin_operation(
    db: Session,
    *,
    user_id: int,
    operation_type: str,
    idempotency_key: str,
    order_id: str | None,
    subdomain: str,
    payload: dict[str, Any],
    fingerprint_payload: dict[str, Any] | None = None,
) -> OrderOperation:
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload_fingerprint = fingerprint(fingerprint_payload or payload)
    existing = get_order_operation(db, user_id=user_id, idempotency_key=idempotency_key)
    if existing is not None:
        _validate_reuse(existing, operation_type, payload_fingerprint)
        existing.attempts += 1
        existing.last_error_code = None
        db.commit()
        db.refresh(existing)
        return existing

    operation = OrderOperation(
        user_id=user_id,
        operation_type=operation_type,
        idempotency_key=idempotency_key,
        order_id=order_id,
        subdomain=subdomain,
        request_fingerprint=payload_fingerprint,
        request_json=payload_json,
        status="pending",
        attempts=1,
    )
    db.add(operation)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = get_order_operation(db, user_id=user_id, idempotency_key=idempotency_key)
        if existing is None:
            raise
        _validate_reuse(existing, operation_type, payload_fingerprint)
        existing.attempts += 1
        db.commit()
        db.refresh(existing)
        return existing
    db.refresh(operation)
    return operation


def _validate_reuse(operation: OrderOperation, operation_type: str, payload_fingerprint: str) -> None:
    if (
        operation.operation_type != operation_type
        or operation.request_fingerprint != payload_fingerprint
    ):
        raise OperationConflict("Idempotency key conflicts with an existing order operation.")


def mark_upstream_confirmed(
    db: Session,
    operation: OrderOperation,
    *,
    order_id: str,
    response: dict[str, Any],
) -> None:
    operation.upstream_order_id = order_id
    operation.response_json = json.dumps(response, sort_keys=True, separators=(",", ":"))
    operation.status = "upstream_confirmed"
    operation.last_error_code = None
    db.commit()
    db.refresh(operation)


def update_operation_request(
    db: Session,
    operation: OrderOperation,
    *,
    payload: dict[str, Any],
) -> None:
    operation.request_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    db.commit()
    db.refresh(operation)


def mark_operation_complete(
    db: Session,
    operation: OrderOperation,
    *,
    response: dict[str, Any],
    commit: bool = True,
) -> None:
    operation.response_json = json.dumps(response, sort_keys=True, separators=(",", ":"))
    operation.status = "completed"
    operation.last_error_code = None
    if commit:
        db.commit()
        db.refresh(operation)


def mark_operation_retryable(db: Session, operation: OrderOperation, *, error_code: str) -> None:
    operation.last_error_code = error_code[:64]
    db.commit()


def operation_response(operation: OrderOperation) -> dict[str, Any] | None:
    if not operation.response_json:
        return None
    try:
        result = json.loads(operation.response_json)
    except (TypeError, json.JSONDecodeError):
        return None
    return result if isinstance(result, dict) else None
