"""Integration tests for balance calculation service and HTTP endpoint."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType
from app.models.entry import Direction, Entry
from app.models.transaction import Transaction, TransactionStatus
from app.services.balance import calculate_balance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# 📋 Copy-paste: same pattern as test_transactions.py _create_account
async def _create_account(
    db: AsyncSession,
    code: str,
    name: str,
    account_type: AccountType,
    currency: str = "EUR",
) -> Account:
    account = Account(code=code, name=name, account_type=account_type, currency=currency)
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


# 📋 Copy-paste: build a POSTED transaction with two entries (debit + credit)
async def _create_posted_transaction(
    db: AsyncSession,
    debit_account: Account,
    credit_account: Account,
    amount: int,
    transaction_date: date,
    currency: str = "EUR",
) -> Transaction:
    tx = Transaction(
        description="test transaction",
        transaction_date=transaction_date,
        status=TransactionStatus.POSTED,
    )
    db.add(tx)
    await db.flush()
    db.add_all([
        Entry(
            transaction_id=tx.id,
            account_id=debit_account.id,
            direction=Direction.DEBIT,
            amount=amount,
            currency=currency,
        ),
        Entry(
            transaction_id=tx.id,
            account_id=credit_account.id,
            direction=Direction.CREDIT,
            amount=amount,
            currency=currency,
        ),
    ])
    await db.commit()
    await db.refresh(tx)
    return tx


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_balance_single_debit_equals_amount(db_session: AsyncSession) -> None:
    # 🔧 TODO: create debit_account (ASSET) and credit_account (LIABILITY)
    #   post a transaction of 1000 on date(2026, 1, 10)
    #   call calculate_balance(db_session, debit_account.id, datetime(2026, 1, 31, tzinfo=timezone.utc))
    #   assert result == 1000
    raise NotImplementedError


@pytest.mark.asyncio
async def test_balance_excludes_transaction_after_as_of(db_session: AsyncSession) -> None:
    # 🔧 TODO: create accounts, post one tx on date(2026, 1, 10) and another on date(2026, 2, 1)
    #   call calculate_balance with as_of = datetime(2026, 1, 31, tzinfo=timezone.utc)
    #   assert only the first tx is reflected (second is excluded)
    raise NotImplementedError


@pytest.mark.asyncio
async def test_balance_excludes_voided_transaction(db_session: AsyncSession) -> None:
    # 🔧 TODO: create accounts, post one POSTED tx and one VOIDED tx (both within as_of range)
    #   assert only POSTED amount is in balance (VOIDED is excluded)
    raise NotImplementedError


@pytest.mark.asyncio
async def test_balance_no_transactions_returns_zero(db_session: AsyncSession) -> None:
    # 🔧 TODO: create an account with no transactions
    #   assert calculate_balance returns 0
    raise NotImplementedError


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_balance_endpoint_returns_correct_value(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    # 🔧 TODO: create accounts via POST /accounts, post a transaction via POST /transactions
    #   GET /accounts/{id}/balance?as_of=2026-01-31T00:00:00
    #   assert response.status_code == 200
    #   assert response.json()["balance"] == <expected int>
    raise NotImplementedError
