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

from app.models.account import Account
from app.models.entry import Entry
# ✍️ replace EntryType import with: from app.models.entry import Direction
# ✍️ add import: from app.models.transaction import Transaction, TransactionStatus
from app.models.entry import EntryType  # TODO: replace with Direction in Step C
from app.models.transaction import Transaction
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
    # 🔧 TODO: update DEBIT/CREDIT attribute access from entry_type → direction
    # hint: replace EntryType.DEBIT → Direction.DEBIT, EntryType.CREDIT → Direction.CREDIT
    debit_sum = sum(
        e.amount for e in payload.entries if e.entry_type == EntryType.DEBIT  # TODO: e.direction == Direction.DEBIT
    )
    credit_sum = sum(
        e.amount for e in payload.entries if e.entry_type == EntryType.CREDIT  # TODO: e.direction == Direction.CREDIT
    )

    if debit_sum != credit_sum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Entries are not balanced: "
                f"debit={debit_sum} credit={credit_sum}"
            ),
        )

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------
    # 🔧 TODO: update Transaction() instantiation
    # hint: remove amount=payload.amount
    #       add status=TransactionStatus.POSTED
    #       add posted_at=datetime.utcnow()  (import datetime from datetime)
    transaction = Transaction(
        description=payload.description,
        transaction_date=payload.transaction_date,
        # amount=payload.amount,  ← REMOVE: no longer on Transaction model
        # TODO: status=TransactionStatus.POSTED,
        # TODO: posted_at=datetime.utcnow(),
    )
    db.add(transaction)
    await db.flush()

    # 🔧 TODO: update Entry() instantiation
    # hint: replace entry_type=entry.entry_type → direction=entry.direction
    #       add currency=entry.currency
    entries = [
        Entry(
            transaction_id=transaction.id,
            account_id=entry.account_id,
            entry_type=entry.entry_type,  # TODO: direction=entry.direction
            amount=entry.amount,
            # TODO: currency=entry.currency,
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
