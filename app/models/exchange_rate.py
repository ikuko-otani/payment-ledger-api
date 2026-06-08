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
    __table_args__ = (
        UniqueConstraint(
            "from_currency_id",
            "to_currency_id",
            "effective_date",
            name="uq_exchange_rate_pair_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    from_currency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("currencies.id"), nullable=False
    )
    to_currency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("currencies.id"), nullable=False
    )
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ExchangeRate {self.from_currency_id}->{self.to_currency_id}"
            f" on {self.effective_date} rate={self.rate}>"
        )
