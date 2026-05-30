"""Audit-logs read endpoint — GET /audit-logs (admin only)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AdminUser
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.schemas.audit_log import AuditLogRead

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[AuditLogRead])
async def get_audit_logs(
    db: DbDep,
    _current_user: AdminUser,
    entity_type: str | None = Query(default=None),
    entity_id: uuid.UUID | None = Query(default=None),
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AuditLog]:
    # 🔧 Build filter list — same pattern as get_ledger_entries (≤10 lines)
    filters = []
    # TODO: if entity_type → append AuditLog.entity_type == entity_type
    # TODO: if entity_id   → append AuditLog.entity_id == entity_id
    # TODO: if from_dt     → append AuditLog.created_at >= from_dt
    # TODO: if to_dt       → append AuditLog.created_at <= to_dt

    # 🔧 Execute query and return (≤5 lines)
    # select(AuditLog).where(*filters).order_by(created_at desc).offset/limit
    # TODO: stmt = select(AuditLog).where(*filters).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    # TODO: result = await db.execute(stmt)
    # TODO: return list(result.scalars().all())
    return []  # placeholder — remove after implementing
