"""AuditLog model — immutable record of create/update/delete operations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """Audit log table — append-only record of state changes.

    Rows are INSERT-only; no UPDATE or DELETE is ever issued by the application.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    entity_type: Mapped[str] = mapped_column(String, nullable=False)

    entity_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=False,
    )

    action: Mapped[str] = mapped_column(String, nullable=False)

    before_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    after_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} "
            f"entity={self.entity_type}/{self.entity_id} "
            f"action={self.action}>"
        )
