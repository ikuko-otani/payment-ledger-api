"""Currency master — ISO 4217 currency definitions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Currency(Base):
    """ISO 4217 currency master table."""

    __tablename__ = "currencies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # ✍️ code
    # ✍️ name
    # ✍️ decimal_places
    # ✍️ is_active
    # ✍️ created_at

    def __repr__(self) -> str:
        return f"<Currency id={self.id}>"
