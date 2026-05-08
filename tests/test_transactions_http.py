"""HTTP layer integration tests for POST /transactions.

These tests exercise the full FastAPI stack (routing -> schema -> service)
via httpx.AsyncClient, proving that the HTTP response code is 422 for
invalid payloads — satisfying the S2-1 DONE condition.

Session lifecycle note:
  Each request gets its own AsyncSession (see conftest.async_client).
  This avoids the asyncpg InterfaceError that occurred in S1-4 when a
  shared session was used across multiple requests.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType


async def _seed_account(
    db_session: AsyncSession,
    name: str,
    account_type: AccountType,
) -> str:
    """Insert an account and return its id as str."""
    account = Account(name=name, account_type=account_type)
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return str(account.id)


@pytest.mark.asyncio
async def test_post_transactions_unbalanced_returns_422(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """DONE condition: unbalanced entries -> HTTP 422."""
    debit_id = await _seed_account(db_session, "Cash-HTTP", AccountType.ASSET)
    credit_id = await _seed_account(db_session, "Revenue-HTTP", AccountType.REVENUE)

    payload = {
        "description": "Unbalanced via HTTP",
        "transaction_date": "2024-01-01",
        "amount": "1000.00",
        "entries": [
            {"account_id": debit_id, "entry_type": "debit", "amount": "1000.00"},
            {"account_id": credit_id, "entry_type": "credit", "amount": "500.00"},
        ],
    }

    response = await async_client.post("/api/v1/transactions", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_transactions_zero_amount_returns_422(
    async_client: AsyncClient,
) -> None:
    """amount=0 in any entry -> HTTP 422 from Pydantic."""
    payload = {
        "description": "Zero amount",
        "transaction_date": "2024-01-01",
        "amount": "0",
        "entries": [
            {"account_id": "11111111-1111-1111-1111-111111111111", "entry_type": "debit", "amount": "0"},
            {"account_id": "22222222-2222-2222-2222-222222222222", "entry_type": "credit", "amount": "0"},
        ],
    }

    response = await async_client.post("/api/v1/transactions", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_transactions_single_entry_returns_422(
    async_client: AsyncClient,
) -> None:
    """Only 1 entry (no double-entry) -> HTTP 422 from Pydantic."""
    payload = {
        "description": "Single entry",
        "transaction_date": "2024-01-01",
        "amount": "500.00",
        "entries": [
            {"account_id": "11111111-1111-1111-1111-111111111111", "entry_type": "debit", "amount": "500.00"},
        ],
    }

    response = await async_client.post("/api/v1/transactions", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_transactions_unknown_account_returns_422(
    async_client: AsyncClient,
) -> None:
    """Non-existent account_id -> HTTP 422 from service layer."""
    payload = {
        "description": "Ghost account",
        "transaction_date": "2024-01-01",
        "amount": "500.00",
        "entries": [
            {"account_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "entry_type": "debit", "amount": "500.00"},
            {"account_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "entry_type": "credit", "amount": "500.00"},
        ],
    }

    response = await async_client.post("/api/v1/transactions", json=payload)

    assert response.status_code == 422
