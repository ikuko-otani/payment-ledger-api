"""Audit service — cross-cutting concern for recording state changes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def log_action(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """Append one immutable audit record to the current session.

    Must be called within the same AsyncSession as the main operation
    to guarantee atomicity: if either write fails, the whole transaction rolls back.
    """
    db.add(
        AuditLog(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before_value=before,
            after_value=after,
        )
    )


async def list_audit_logs(
    db: AsyncSession,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[AuditLog]:
    filters = []
    if entity_type:
        filters.append(AuditLog.entity_type == entity_type)
    if entity_id:
        filters.append(AuditLog.entity_id == entity_id)
    if from_dt:
        filters.append(AuditLog.created_at >= from_dt)
    if to_dt:
        filters.append(AuditLog.created_at <= to_dt)

    stmt = (
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
