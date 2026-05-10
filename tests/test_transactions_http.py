"""HTTP layer integration tests for POST /transactions.

These tests exercise the full FastAPI stack (routing -> schema -> service)
via httpx.AsyncClient, proving that the HTTP response code is 422 for
invalid payloads — satisfying the S2-1 DONE condition.

S2-2 additions:
  - test_post_transactions_returns_201_with_id : happy path, DONE condition
  - test_get_transactions_returns_list_shape   : GET response shape check
  - test_post_then_get_shows_persisted_record  : persistence confirmation

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
            {
                "account_id": "11111111-1111-1111-1111-111111111111",
                "entry_type": "debit",
                "amount": "0",
            },
            {
                "account_id": "22222222-2222-2222-2222-222222222222",
                "entry_type": "credit",
                "amount": "0",
            },
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
            {
                "account_id": "11111111-1111-1111-1111-111111111111",
                "entry_type": "debit",
                "amount": "500.00",
            },
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
            {
                "account_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "entry_type": "debit",
                "amount": "500.00",
            },
            {
                "account_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "entry_type": "credit",
                "amount": "500.00",
            },
        ],
    }

    response = await async_client.post("/api/v1/transactions", json=payload)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# S2-2: Happy path and persistence tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_transactions_returns_201_with_id(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """DONE condition (S2-2): valid double-entry payload -> HTTP 201 + id in response."""
    # Seed two accounts using _seed_account, build a balanced payload,
    # POST to /api/v1/transactions, assert status 201 and "id" in response JSON
    # 1. _seed_account でアカウントを2つ作る（debit用 / credit用）
    # 2. balanced payload を組み立てる
    # 3. POST して status_code == 201 を確認
    # 4. body["id"] が存在することと、entries が2件あることを確認
    debit_id = await _seed_account(db_session, "Cash-201", AccountType.ASSET)
    credit_id = await _seed_account(db_session, "Revenue-201", AccountType.REVENUE)

    payload = {
        "description": "Sales receipt",
        "transaction_date": "2024-06-01",
        "amount": "5000.00",
        "entries": [
            {"account_id": debit_id, "entry_type": "debit", "amount": "5000.00"},
            {"account_id": credit_id, "entry_type": "credit", "amount": "5000.00"},
        ],
    }

    response = await async_client.post("/api/v1/transactions", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["description"] == "Sales receipt"
    assert len(body["entries"]) == 2


@pytest.mark.asyncio
async def test_get_transactions_returns_list_shape(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /transactions returns a list; each item has id, description, entries."""
    debit_id = await _seed_account(db_session, "Cash-GET", AccountType.ASSET)
    credit_id = await _seed_account(db_session, "Revenue-GET", AccountType.REVENUE)

    post_payload = {
        "description": "GET shape check",
        "transaction_date": "2024-06-02",
        "amount": "300.00",
        "entries": [
            {"account_id": debit_id, "entry_type": "debit", "amount": "300.00"},
            {"account_id": credit_id, "entry_type": "credit", "amount": "300.00"},
        ],
    }
    await async_client.post("/api/v1/transactions", json=post_payload)

    response = await async_client.get("/api/v1/transactions")

    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    assert len(items) >= 1
    first = items[0]
    assert "id" in first
    assert "entries" in first


@pytest.mark.asyncio
async def test_post_then_get_shows_persisted_record(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Persistence check: record created via POST is visible via GET."""
    # POST a transaction, extract the returned id,
    # GET /transactions, assert the id appears in the list
    debit_id = await _seed_account(db_session, "Cash-Persist", AccountType.ASSET)
    credit_id = await _seed_account(db_session, "Revenue-Persist", AccountType.REVENUE)

    post_payload = {
        "description": "Persistence test",
        "transaction_date": "2024-06-03",
        "amount": "1200.00",
        "entries": [
            {"account_id": debit_id, "entry_type": "debit", "amount": "1200.00"},
            {"account_id": credit_id, "entry_type": "credit", "amount": "1200.00"},
        ],
    }

    post_resp = await async_client.post("/api/v1/transactions", json=post_payload)
    assert post_resp.status_code == 201
    created_id = post_resp.json()["id"]

    get_resp = await async_client.get("/api/v1/transactions")
    assert get_resp.status_code == 200
    ids_in_list = [item["id"] for item in get_resp.json()]
    assert created_id in ids_in_list
