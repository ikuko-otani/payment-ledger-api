"""Transaction model — a double-entry transaction header.

One Transaction links to two or more Entry rows (debit + credit).
Balance rule (debit == credit) is enforced at the service layer (S1-2).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Transaction(Base):
    """Transaction header table."""

    __tablename__ = "transactions"

    # 🔧 穴埋め: mapped_column() の引数を完成させてください
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    description: Mapped[str] = mapped_column(
        # TODO: ここを実装（ヒント: nullable=False）
        nullable=False,
    )
    transaction_date: Mapped[date] = mapped_column(
        # TODO: ここを実装（ヒント: nullable=False。Python の date 型で OK）
        nullable=False,
    )
    # 💡 金融システムでは Decimal / Numeric を使う。Float は浮動小数点誤差が出るため NG。
    #    precision=18（整数部）, scale=4（小数点以下4桁）は国際会計基準を意識した設定。
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=4),
        # TODO: ここを実装（ヒント: nullable=False）
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} "
            f"date={self.transaction_date} amount={self.amount}>"
        )
