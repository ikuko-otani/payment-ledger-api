"""Transaction model — a double-entry transaction header.

One Transaction links to two or more Entry rows (debit + credit).
Balance rule (debit_sum == credit_sum) is enforced at the DB level
via a CHECK constraint added in the S1-2 Alembic migration.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.entry import Entry


class Transaction(Base):
    """Transaction header table."""

    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    description: Mapped[str] = mapped_column(
        nullable=False,
    )
    transaction_date: Mapped[date] = mapped_column(
        nullable=False,
    )
    # 💡 Numeric(18, 4): 18 significant digits, 4 decimal places.
    #    Avoids floating-point rounding errors critical in financial systems.
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=4),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )

    # TODO: entries リレーションを定義する
    #   ヒント: Mapped[list["Entry"]], back_populates="transaction",
    #           cascade="all, delete-orphan"
    entries: Mapped[list["Entry"]] = relationship(
        # back_populates を設定
        # entry.py で定義した属性名
        back_populates="transaction",
        # cascade を設定
        # 親Transactionを消したらEntryも消えてほしい
        cascade="all, delete-orphan",
        # lazy loading の設定
        # "select" でOK、デフォルト値
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} "
            f"date={self.transaction_date} amount={self.amount}>"
        )
