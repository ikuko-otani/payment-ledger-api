"""Transaction service — orchestrates DB writes and enforces double-entry rule.

Validation responsibilities:
  - Double-entry balance : debit_sum == credit_sum  (primary check, enforced here)
  - account_id existence : each entry.account_id must exist in accounts table
  - Value shape          : delegated to Pydantic schemas (amount > 0, etc.)

A deferred CONSTRAINT TRIGGER (trg_check_entries_balance) re-checks balance
at COMMIT as a DB-level safety net for writes that bypass this service layer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.core.exceptions import ConflictError, ValidationError
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


async def void_transaction(
    tx_repo: TransactionRepository,
    audit_repo: AuditRepository,
    transaction_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[Transaction, Transaction] | None:
    """Mark a POSTED transaction as VOIDED and create a balanced reversal.

    Returns (voided_original, reversal_transaction).
    Raises ConflictError(409) if the transaction is already VOIDED.
    Returns None for the original if not found (caller raises 404).
    """
    original = await tx_repo.find_by_id_with_entries(transaction_id)
    if original is None:
        return None  # caller must check

    before_value: dict[str, Any] = {
        "id": str(original.id),
        "status": original.status.value,
        "description": original.description,
        "transaction_date": str(original.transaction_date),
    }

    # Atomic CAS: only succeeds if status was still POSTED at write time.
    # Guards against the TOCTOU race where two concurrent voids both pass
    # a plain status check before either commits (see ADR-002).
    voided = await tx_repo.mark_voided_if_posted(transaction_id)
    if not voided:
        raise ConflictError(detail=f"Transaction {transaction_id} is already voided")

    # Keep the in-memory object in sync with the DB write above, since the
    # Core-style UPDATE does not update the already-loaded ORM instance.
    original.status = TransactionStatus.VOIDED

    # Build reversal transaction with opposite entry directions
    reversal = Transaction(
        description=f"Reversal of: {original.description}",
        transaction_date=original.transaction_date,
        status=TransactionStatus.POSTED,
        posted_at=datetime.now(UTC),
        metadata_={"reversal_of": str(original.id)},
    )
    reversal_entries = [
        Entry(
            account_id=entry.account_id,
            direction=(
                Direction.CREDIT
                if entry.direction == Direction.DEBIT
                else Direction.DEBIT
            ),
            amount=entry.amount,
            currency=entry.currency,
            converted_amount_usd=entry.converted_amount_usd,
        )
        for entry in original.entries
    ]

    loaded_reversal = await tx_repo.save(reversal, reversal_entries)

    # Audit log for the reversal creation — allows investigators to locate
    # the reversal by its own entity_id, not just via the void log's after value.
    await audit_repo.log(
        user_id=user_id,
        entity_type="transaction",
        entity_id=loaded_reversal.id,
        action="create",
        before=None,
        after={
            "id": str(loaded_reversal.id),
            "description": loaded_reversal.description,
            "status": loaded_reversal.status.value,
            "reversal_of": str(original.id),
        },
    )

    await audit_repo.log(
        user_id=user_id,
        entity_type="transaction",
        entity_id=original.id,
        action="void",
        before=before_value,
        after={
            "id": str(original.id),
            "status": original.status.value,
            "reversal_transaction_id": str(loaded_reversal.id),
        },
    )
    return original, loaded_reversal
