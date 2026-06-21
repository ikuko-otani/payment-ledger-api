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

from app.core.exceptions import ValidationError
from app.models.entry import Direction, Entry
from app.models.transaction import Transaction, TransactionStatus
from app.repositories.account_repository import AccountRepository
from app.repositories.audit_repository import AuditRepository
from app.repositories.currency_repository import CurrencyRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.transaction import TransactionCreate

# Base currency: all amounts are converted to USD cents at write time.
# Changing this constant requires a full data migration — treat as immutable.
BASE_CURRENCY = "USD"


async def _resolve_usd_conversion_rate(
    currency_repo: CurrencyRepository,
    currency_code: str,
    transaction_date: date,
) -> Decimal:
    """Resolve the conversion rate from currency_code to USD for transaction_date.

    - If currency_code == BASE_CURRENCY: returns Decimal("1") (identity, no query).
    - Otherwise: looks up ExchangeRate(from=currency_code, to=USD, date=transaction_date)
      and returns its `rate`.
    - Raises ValidationError if currency_code/USD is unknown, or no matching rate exists.

    Called once per transaction (not once per entry) -- currency_code and
    transaction_date are transaction-level values shared by every entry.
    """
    if currency_code == BASE_CURRENCY:
        return Decimal("1")

    from_currency = await currency_repo.find_by_code(currency_code)
    if from_currency is None:
        raise ValidationError(detail=f"Unknown currency code: {currency_code!r}")

    to_currency = await currency_repo.find_by_code(BASE_CURRENCY)
    if to_currency is None:
        raise ValidationError(
            detail=f"Base currency {BASE_CURRENCY!r} not found in currencies table"
        )

    exchange_rate = await currency_repo.find_exchange_rate(
        from_currency.id, to_currency.id, transaction_date
    )
    if exchange_rate is None:
        raise ValidationError(
            detail=(
                f"No exchange rate found for {currency_code}→{BASE_CURRENCY} "
                f"on or before {transaction_date}"
            )
        )

    return exchange_rate.rate


def _convert_amount_usd(amount: int, rate: Decimal) -> int:
    """Apply a USD conversion rate to a minor-unit amount (no DB access)."""
    converted = (Decimal(amount) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(converted)


async def create_transaction(
    account_repo: AccountRepository,
    currency_repo: CurrencyRepository,
    tx_repo: TransactionRepository,
    audit_repo: AuditRepository,
    payload: TransactionCreate,
    user_id: uuid.UUID,
) -> Transaction:
    """Validate double-entry balance and persist Transaction + Entries."""

    # ------------------------------------------------------------------
    # Validate: all account_ids must exist in the accounts table
    # ------------------------------------------------------------------
    account_ids = {e.account_id for e in payload.entries}
    found_ids = await account_repo.find_active_by_ids(account_ids)
    missing = account_ids - found_ids.keys()
    if missing:
        raise ValidationError(
            detail=f"Unknown or inactive account_ids: {[str(i) for i in missing]}"
        )

    # ------------------------------------------------------------------
    # Validate: both debit and credit directions must be present
    # ------------------------------------------------------------------
    directions = {e.direction for e in payload.entries}
    if Direction.DEBIT not in directions or Direction.CREDIT not in directions:
        raise ValidationError(
            detail="Entries must include at least one debit and one credit"
        )

    # ------------------------------------------------------------------
    # Validate: all entries must use the same currency
    # ------------------------------------------------------------------
    currencies = {e.currency for e in payload.entries}
    if len(currencies) > 1:
        raise ValidationError(
            detail=f"All entries must use the same currency, got: {sorted(currencies)}"
        )

    # ------------------------------------------------------------------
    # Validate: each entry's currency must match its account's currency (TD-024)
    # ------------------------------------------------------------------
    mismatched = [e for e in payload.entries if e.currency != found_ids[e.account_id]]
    if mismatched:
        raise ValidationError(
            detail=(
                "Entry currency does not match account currency: "
                + ", ".join(
                    f"account_id={e.account_id} entry_currency={e.currency} "
                    f"account_currency={found_ids[e.account_id]}"
                    for e in mismatched
                )
            )
        )

    # ------------------------------------------------------------------
    # Validate: double-entry balance (amounts are now int — minor units)
    # ------------------------------------------------------------------
    debit_sum = sum(e.amount for e in payload.entries if e.direction == Direction.DEBIT)
    credit_sum = sum(
        e.amount for e in payload.entries if e.direction == Direction.CREDIT
    )

    if debit_sum != credit_sum:
        raise ValidationError(
            detail=(f"Entries are not balanced: debit={debit_sum} credit={credit_sum}")
        )

    # ------------------------------------------------------------------
    # Build domain objects
    # ------------------------------------------------------------------
    transaction = Transaction(
        description=payload.description,
        transaction_date=payload.transaction_date,
        status=TransactionStatus.POSTED,
        posted_at=datetime.now(UTC),
    )

    # ------------------------------------------------------------------
    # Resolve USD conversion rate once per transaction
    # ------------------------------------------------------------------
    conversion_rate = await _resolve_usd_conversion_rate(
        currency_repo, payload.currency_code, payload.transaction_date
    )
    converted_amounts = [
        _convert_amount_usd(entry.amount, conversion_rate) for entry in payload.entries
    ]

    # transaction_id is set by tx_repo.save() after the first flush
    entries = [
        Entry(
            account_id=entry.account_id,
            direction=entry.direction,
            amount=entry.amount,
            currency=entry.currency,
            converted_amount_usd=converted_amount,
        )
        for entry, converted_amount in zip(
            payload.entries, converted_amounts, strict=True
        )
    ]

    # ------------------------------------------------------------------
    # Persist via repository
    # ------------------------------------------------------------------
    loaded = await tx_repo.save(transaction, entries)

    after_value: dict[str, Any] = {
        "id": str(loaded.id),
        "description": loaded.description,
        "status": loaded.status.value,
        "transaction_date": str(loaded.transaction_date),
    }
    await audit_repo.log(
        user_id=user_id,
        entity_type="transaction",
        entity_id=loaded.id,
        action="create",
        before=None,
        after=after_value,
    )
    return loaded
