"""Balance service — aggregate balance for a single account up to a given date."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entry import Direction, Entry
from app.models.transaction import Transaction, TransactionStatus


# ✍️ Write the function signature (async def, 3 params → int return type)
async def calculate_balance(
    db: AsyncSession,
    account_id: uuid.UUID,
    as_of: datetime,
) -> int:
    """Return balance (minor units) for account_id up to as_of (inclusive).

    Balance = SUM(debit entries) - SUM(credit entries)
    Only POSTED transactions on or before as_of.date() are included.
    """
    result = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    case((Entry.direction == Direction.DEBIT, Entry.amount), else_=0)
                ),
                0,
            )
            - func.coalesce(
                func.sum(
                    case((Entry.direction == Direction.CREDIT, Entry.amount), else_=0)
                ),
                0,
            )
        )
        .join(Transaction, Entry.transaction_id == Transaction.id)
        .where(
            Entry.account_id == account_id,
            Transaction.transaction_date <= as_of.date(),
            Transaction.status == TransactionStatus.POSTED,
        )
    )
    return result.scalar_one()
