"""HTTP layer integration tests for POST /transactions."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType


async def _seed_account(
    db_session: AsyncSession,
    name: str,
    account_type: AccountType,
    # ✍️ add: code: str, currency: str = "EUR"
) -> str:
    """Insert an account and return its id as str."""
    account = Account(
        # ✍️ add: code=code, currency=currency
        name=name,
        account_type=account_type,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return str(account.id)


@pytest.mark.asyncio
async def test_post_transactions_unbalanced_returns_422(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    debit_id = await _seed_account(db_session, "Cash-HTTP", AccountType.ASSET)  # ✍️ add code="1100"
    credit_id = await _seed_account(db_session, "Revenue-HTTP", AccountType.REVENUE)  # ✍️ add code="4000"

    payload = {
        "description": "Unbalanced via HTTP",
        "transaction_date": "2024-01-01",
        # "amount" removed from transaction level
        "entries": [
            {"account_id": debit_id, "direction": "debit", "amount": 1000, "currency": "EUR"},
            {"account_id": credit_id, "direction": "credit", "amount": 500, "currency": "EUR"},
        ],
    }

    response = await async_client.post("/api/v1/transactions", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_transactions_zero_amount_returns_422(
    async_client: AsyncClient,
) -> None:
    payload = {
        "description": "Zero amount",
        "transaction_date": "2024-01-01",
        "entries": [
            {
                "account_id": "11111111-1111-1111-1111-111111111111",
                "direction": "debit",
                "amount": 0,
                "currency": "EUR",
            },
            {
                "account_id": "22222222-2222-2222-2222-222222222222",
                "direction": "credit",
                "amount": 0,
                "currency": "EUR",
            },
        ],
    }

    response = await async_client.post("/api/v1/transactions", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_transactions_single_entry_returns_422(
    async_client: AsyncClient,
) -> None:
    payload = {
        "description": "Single entry",
        "transaction_date": "2024-01-01",
        "entries": [
            {
                "account_id": "11111111-1111-1111-1111-111111111111",
                "direction": "debit",
                "amount": 500,
                "currency": "EUR",
            },
        ],
    }

    response = await async_client.post("/api/v1/transactions", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_transactions_unknown_account_returns_422(
    async_client: AsyncClient,
) -> None:
    payload = {
        "description": "Ghost account",
        "transaction_date": "2024-01-01",
        "entries": [
            {
                "account_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "direction": "debit",
                "amount": 500,
                "currency": "EUR",
            },
            {
                "account_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "direction": "credit",
                "amount": 500,
                "currency": "EUR",
            },
        ],
    }

    response = await async_client.post("/api/v1/transactions", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_transactions_returns_201_with_id(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    debit_id = await _seed_account(db_session, "Cash-201", AccountType.ASSET)  # ✍️ add code="1101"
    credit_id = await _seed_account(db_session, "Revenue-201", AccountType.REVENUE)  # ✍️ add code="4001"

    payload = {
        "description": "Sales receipt",
        "transaction_date": "2024-06-01",
        "entries": [
            {"account_id": debit_id, "direction": "debit", "amount": 5000, "currency": "EUR"},
            {"account_id": credit_id, "direction": "credit", "amount": 5000, "currency": "EUR"},
        ],
    }

    response = await async_client.post("/api/v1/transactions", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["description"] == "Sales receipt"
    assert len(body["entries"]) == 2
    # ✍️ add: assert body["status"] == "posted"
    # ✍️ add: assert "amount" not in body  (transaction-level amount was removed)


@pytest.mark.asyncio
async def test_get_transactions_returns_list_shape(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    debit_id = await _seed_account(db_session, "Cash-GET", AccountType.ASSET)  # ✍️ add code="1102"
    credit_id = await _seed_account(db_session, "Revenue-GET", AccountType.REVENUE)  # ✍️ add code="4002"

    post_payload = {
        "description": "GET shape check",
        "transaction_date": "2024-06-02",
        "entries": [
            {"account_id": debit_id, "direction": "debit", "amount": 300, "currency": "EUR"},
            {"account_id": credit_id, "direction": "credit", "amount": 300, "currency": "EUR"},
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
    debit_id = await _seed_account(db_session, "Cash-Persist", AccountType.ASSET)  # ✍️ add code="1103"
    credit_id = await _seed_account(db_session, "Revenue-Persist", AccountType.REVENUE)  # ✍️ add code="4003"

    post_payload = {
        "description": "Persistence test",
        "transaction_date": "2024-06-03",
        "entries": [
            {"account_id": debit_id, "direction": "debit", "amount": 1200, "currency": "EUR"},
            {"account_id": credit_id, "direction": "credit", "amount": 1200, "currency": "EUR"},
        ],
    }

    post_resp = await async_client.post("/api/v1/transactions", json=post_payload)
    assert post_resp.status_code == 201
    created_id = post_resp.json()["id"]

    get_resp = await async_client.get("/api/v1/transactions")
    assert get_resp.status_code == 200
    ids_in_list = [item["id"] for item in get_resp.json()]
    assert created_id in ids_in_list
