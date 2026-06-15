"""Audit-logs read endpoint — GET /audit-logs (admin only)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AdminUser
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.schemas.audit_log import AuditLogRead
from app.services import audit_service

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
    return await audit_service.list_audit_logs(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=limit,
        offset=offset,
    )
