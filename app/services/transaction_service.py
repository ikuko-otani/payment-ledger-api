"""Transaction service — orchestrates DB writes and enforces double-entry rule.

Validation responsibilities:
  - Double-entry balance : debit_sum == credit_sum  (enforced here)
  - account_id existence : each entry.account_id must exist in accounts table
  - Value shape          : delegated to Pydantic schemas (amount > 0, etc.)

PostgreSQL CHECK cannot aggregate across rows, so balance is enforced here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi import HTTPException, status

from datetime import datetime, timezone

from app.models.account import Account
from app.models.entry import Entry, Direction
from app.models.transaction import Transaction, TransactionStatus
from app.schemas.transaction import TransactionCreate


async def create_transaction(
    db: AsyncSession,
    payload: TransactionCreate,
) -> Transaction:
    """Validate double-entry balance and persist Transaction + Entries."""

    # ------------------------------------------------------------------
    # Validate: all account_ids must exist in the accounts table
    # ------------------------------------------------------------------
    account_ids = {e.account_id for e in payload.entries}
    result = await db.execute(select(Account).where(Account.id.in_(account_ids)))
    found_ids = {row.id for row in result.scalars().all()}
    missing = account_ids - found_ids
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown account_ids: {[str(i) for i in missing]}",
        )

    # ------------------------------------------------------------------
    # Validate: double-entry balance (amounts are now int — minor units)
    # ------------------------------------------------------------------
    directions = {e.direction for e in payload.entries}
    if Direction.DEBIT not in directions or Direction.CREDIT not in directions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Entries must include at least one debit and one credit",
        )

    debit_sum = sum(e.amount for e in payload.entries if e.direction == Direction.DEBIT)
    credit_sum = sum(
        e.amount for e in payload.entries if e.direction == Direction.CREDIT
    )

    if debit_sum != credit_sum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Entries are not balanced: " f"debit={debit_sum} credit={credit_sum}"
            ),
        )

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------
    transaction = Transaction(
        description=payload.description,
        transaction_date=payload.transaction_date,
        status=TransactionStatus.POSTED,
        posted_at=datetime.now(timezone.utc),
    )
    db.add(transaction)
    await db.flush()

    entries = [
        Entry(
            transaction_id=transaction.id,
            account_id=entry.account_id,
            direction=entry.direction,
            amount=entry.amount,
            currency=entry.currency,
        )
        for entry in payload.entries
    ]
    db.add_all(entries)
    await db.flush()

    result = await db.execute(
        select(Transaction)
        .where(Transaction.id == transaction.id)
        .options(selectinload(Transaction.entries))
    )
    return result.scalar_one()
