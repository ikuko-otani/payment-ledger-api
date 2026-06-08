"""Transaction service — orchestrates DB writes and enforces double-entry rule.

Validation responsibilities:
  - Double-entry balance : debit_sum == credit_sum  (enforced here)
  - account_id existence : each entry.account_id must exist in accounts table
  - Value shape          : delegated to Pydantic schemas (amount > 0, etc.)

PostgreSQL CHECK cannot aggregate across rows, so balance is enforced here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

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
from app.services.audit_service import log_action

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
    """
    if currency_code == BASE_CURRENCY:
        return amount

    # Resolve from_currency UUID
    from_result = await db.execute(select(Currency).where(Currency.code == currency_code))
    from_currency = from_result.scalar_one_or_none()
    if from_currency is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown currency code: {currency_code!r}",
        )

    # Resolve to_currency (USD) UUID
    to_result = await db.execute(select(Currency).where(Currency.code == BASE_CURRENCY))
    to_currency = to_result.scalar_one_or_none()
    if to_currency is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Base currency {BASE_CURRENCY!r} not found in currencies table",
        )

    # Look up ExchangeRate for (from, to, date)
    rate_result = await db.execute(
        select(ExchangeRate).where(
            ExchangeRate.from_currency_id == from_currency.id,
            ExchangeRate.to_currency_id == to_currency.id,
            ExchangeRate.effective_date == transaction_date,
        )
    )
    exchange_rate = rate_result.scalar_one_or_none()
    if exchange_rate is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"No exchange rate found for {currency_code}→{BASE_CURRENCY} on {transaction_date}"
            ),
        )

    converted = (Decimal(amount) * exchange_rate.rate).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(converted)


async def create_transaction(
    db: AsyncSession,
    payload: TransactionCreate,
    user_id: uuid.UUID,
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
        posted_at=datetime.now(UTC),
    )
    db.add(transaction)
    await db.flush()

    # ------------------------------------------------------------------
    # Convert each entry amount to USD cents at write time
    # ------------------------------------------------------------------
    converted_amounts = [
        await _get_converted_amount_usd(
            db, entry.amount, payload.currency_code, payload.transaction_date
        )
        for entry in payload.entries
    ]

    entries = [
        Entry(
            transaction_id=transaction.id,
            account_id=entry.account_id,
            direction=entry.direction,
            amount=entry.amount,
            currency=entry.currency,
            converted_amount_usd=converted_amount,
        )
        for entry, converted_amount in zip(payload.entries, converted_amounts)
    ]
    db.add_all(entries)
    await db.flush()

    tx_result = await db.execute(
        select(Transaction)
        .where(Transaction.id == transaction.id)
        .options(selectinload(Transaction.entries))
    )
    loaded = tx_result.scalar_one()

    after_value: dict[str, Any] = {
        "id": str(loaded.id),
        "description": loaded.description,
        "status": loaded.status.value,
        "transaction_date": str(loaded.transaction_date),
    }
    await log_action(
        db,
        user_id=user_id,
        entity_type="transaction",
        entity_id=loaded.id,
        action="create",
        before=None,
        after=after_value,
    )
    return loaded
