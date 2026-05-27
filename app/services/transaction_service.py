"""Transaction service — orchestrates DB writes and enforces double-entry rule.

Validation responsibilities:
  - Double-entry balance : debit_sum == credit_sum  (enforced here)
  - account_id existence : each entry.account_id must exist in accounts table
  - Value shape          : delegated to Pydantic schemas (amount > 0, etc.)

PostgreSQL CHECK cannot aggregate across rows, so balance is enforced here.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import Account
from app.models.currency import Currency
from app.models.entry import Direction, Entry
from app.models.exchange_rate import ExchangeRate
from app.models.transaction import Transaction, TransactionStatus
from app.schemas.transaction import TransactionCreate

# Base currency: all amounts are converted to USD cents at write time.
# Changing this constant requires a full data migration — treat as immutable.
BASE_CURRENCY = "USD"


async def _get_converted_amount_usd(
    db: AsyncSession,
    amount: int,
    currency_code: str,
    transaction_date: date,
) -> int:
    """Return the USD-cent equivalent of `amount` in `currency_code`.

    - If currency_code == BASE_CURRENCY: returns amount unchanged (identity).
    - Otherwise: looks up ExchangeRate(from=currency_code, to=USD, date=transaction_date)
      and applies ROUND_HALF_UP rounding.
    - Raises HTTP 422 if no matching ExchangeRate row exists.

    ✍️ TODO: implement — see Step C for full implementation
    """
    ...


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
    # Validate: both debit and credit directions must be present
    # ------------------------------------------------------------------
    directions = {e.direction for e in payload.entries}
    if Direction.DEBIT not in directions or Direction.CREDIT not in directions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Entries must include at least one debit and one credit",
        )

    # ------------------------------------------------------------------
    # Validate: all entries must use the same currency
    # ------------------------------------------------------------------
    currencies = {e.currency for e in payload.entries}
    if len(currencies) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"All entries must use the same currency, got: {sorted(currencies)}",
        )

    # ------------------------------------------------------------------
    # Validate: double-entry balance (amounts are now int — minor units)
    # ------------------------------------------------------------------
    debit_sum = sum(e.amount for e in payload.entries if e.direction == Direction.DEBIT)
    credit_sum = sum(e.amount for e in payload.entries if e.direction == Direction.CREDIT)

    if debit_sum != credit_sum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(f"Entries are not balanced: debit={debit_sum} credit={credit_sum}"),
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

    # ------------------------------------------------------------------
    # Convert each entry amount to USD cents at write time
    # ✍️ TODO: call _get_converted_amount_usd for each entry — see Step C
    # ------------------------------------------------------------------

    entries = [
        Entry(
            transaction_id=transaction.id,
            account_id=entry.account_id,
            direction=entry.direction,
            amount=entry.amount,
            currency=entry.currency,
            converted_amount_usd=0,  # ✍️ TODO: replace with conversion result
        )
        for entry in payload.entries
    ]
    db.add_all(entries)
    await db.flush()

    tx_result = await db.execute(
        select(Transaction)
        .where(Transaction.id == transaction.id)
        .options(selectinload(Transaction.entries))
    )
    return tx_result.scalar_one()
