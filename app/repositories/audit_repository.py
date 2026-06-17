"""Audit repository — abstract interface and SQLAlchemy implementation."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.audit_log import AuditLog


class AuditRepository(ABC):
    @abstractmethod
    async def log(
        self,
        user_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None: ...

    @abstractmethod
    async def list_logs(
        self,
        entity_type: str | None,
        entity_id: uuid.UUID | None,
        from_dt: datetime | None,
        to_dt: datetime | None,
        limit: int,
        offset: int,
    ) -> list[AuditLog]: ...


class SQLAlchemyAuditRepository(AuditRepository):
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def log(
        self,
        user_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        self._db.add(
            AuditLog(
                user_id=user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                before_value=before,
                after_value=after,
            )
        )

    async def list_logs(
        self,
        entity_type: str | None,
        entity_id: uuid.UUID | None,
        from_dt: datetime | None,
        to_dt: datetime | None,
        limit: int,
        offset: int,
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
        result = await self._db.execute(stmt)
        return list(result.scalars().all())


def get_audit_repository(
    db: AsyncSession = Depends(get_db),
) -> AuditRepository:
    return SQLAlchemyAuditRepository(db)
