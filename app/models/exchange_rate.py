"""ExchangeRate model — point-in-time FX rates between currency pairs."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExchangeRate(Base):
    """FX rate table. One row per (from_currency, to_currency, effective_date)."""

    __tablename__ = "exchange_rates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # ✍️ from_currency_id
    # ✍️ to_currency_id
    # ✍️ rate
    # ✍️ effective_date
    # ✍️ created_by_id
    # ✍️ created_at

    def __repr__(self) -> str:
        return f"<ExchangeRate id={self.id}>"
