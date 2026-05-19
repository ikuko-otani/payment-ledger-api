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


# Same pattern as test_transactions.py _create_account
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


# Build a POSTED transaction with two entries (debit + credit)
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
    db.add_all(
        [
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
        ]
    )
    await db.commit()
    await db.refresh(tx)
    return tx


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_balance_single_debit_equals_amount(db_session: AsyncSession) -> None:
    cash = await _create_account(db_session, "1101", "Cash", AccountType.ASSET)
    revenue = await _create_account(db_session, "4001", "Revenue", AccountType.REVENUE)

    await _create_posted_transaction(
        db_session, cash, revenue, amount=1000, transaction_date=date(2026, 1, 10)
    )

    result = await calculate_balance(
        db_session, cash.id, datetime(2026, 1, 31, tzinfo=timezone.utc)
    )
    assert result == 1000


@pytest.mark.asyncio
async def test_balance_excludes_transaction_after_as_of(
    db_session: AsyncSession,
) -> None:
    cash = await _create_account(db_session, "1101", "Cash", AccountType.ASSET)
    revenue = await _create_account(db_session, "4001", "Revenue", AccountType.REVENUE)

    await _create_posted_transaction(
        db_session, cash, revenue, amount=1000, transaction_date=date(2026, 1, 31)
    )
    await _create_posted_transaction(
        db_session, cash, revenue, amount=500, transaction_date=date(2026, 2, 1)
    )

    result = await calculate_balance(
        db_session, cash.id, datetime(2026, 1, 31, tzinfo=timezone.utc)
    )
    assert result == 1000  # assert only the first tx is reflected (second is excluded)


@pytest.mark.asyncio
async def test_balance_excludes_voided_transaction(db_session: AsyncSession) -> None:
    cash = await _create_account(db_session, "1101", "Cash", AccountType.ASSET)
    revenue = await _create_account(db_session, "4001", "Revenue", AccountType.REVENUE)

    await _create_posted_transaction(
        db_session, cash, revenue, amount=1000, transaction_date=date(2026, 1, 10)
    )

    # VOIDED tx (within as_of range)
    voided_tx = Transaction(
        description="voided tx",
        transaction_date=date(2026, 1, 15),
        status=TransactionStatus.VOIDED,
    )
    db_session.add(voided_tx)
    await db_session.flush()
    db_session.add_all(
        [
            Entry(
                transaction_id=voided_tx.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=200,
                currency="EUR",
            ),
            Entry(
                transaction_id=voided_tx.id,
                account_id=revenue.id,
                direction=Direction.CREDIT,
                amount=200,
                currency="EUR",
            ),
        ]
    )
    await db_session.commit()

    result = await calculate_balance(
        db_session, cash.id, datetime(2026, 1, 31, tzinfo=timezone.utc)
    )
    assert result == 1000  # assert only POSTED amount is in balance (VOIDED is excluded)


@pytest.mark.asyncio
async def test_balance_no_transactions_returns_zero(db_session: AsyncSession) -> None:
    # Create an account with no transactions
    cash = await _create_account(db_session, "1101", "Cash", AccountType.ASSET)

    result = await calculate_balance(
        db_session, cash.id, datetime(2026, 1, 31, tzinfo=timezone.utc)
    )
    assert result == 0


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_balance_endpoint_returns_correct_value(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    # Create accounts via POST /accounts
    resp = await async_client.post(
        "/api/v1/accounts",
        json={
            "code": "1101",
            "name": "Cash",
            "account_type": "asset",
            "currency": "EUR",
        },
    )
    assert resp.status_code == 201
    cash_id = resp.json()["id"]

    resp = await async_client.post(
        "/api/v1/accounts",
        json={
            "code": "4000",
            "name": "Revenue",
            "account_type": "revenue",
            "currency": "EUR",
        },
    )
    assert resp.status_code == 201
    revenue_id = resp.json()["id"]

    # Post a transaction via POST /transactions
    resp = await async_client.post(
        "/api/v1/transactions",
        json={
            "description": "test sale",
            "transaction_date": "2026-01-10",
            "entries": [
                {
                    "account_id": cash_id,
                    "direction": "debit",
                    "amount": 2500,
                    "currency": "EUR",
                },
                {
                    "account_id": revenue_id,
                    "direction": "credit",
                    "amount": 2500,
                    "currency": "EUR",
                },
            ],
        },
    )
    assert resp.status_code == 201

    resp = await async_client.get(
        f"/api/v1/accounts/{cash_id}/balance",
        params={"as_of": "2026-01-31T00:00:00"},
    )
    assert resp.status_code == 200
    assert resp.json()["balance"] == 2500
