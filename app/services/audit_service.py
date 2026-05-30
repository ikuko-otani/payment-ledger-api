"""Audit service — cross-cutting concern for recording state changes."""

from __future__ import annotations

import uuid
from typing import Any

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
