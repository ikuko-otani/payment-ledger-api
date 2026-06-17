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
    code: str,
    currency: str = "EUR",
) -> str:
    """Insert an account and return its id as str."""
    account = Account(
        name=name,
        account_type=account_type,
        code=code,
        currency=currency,
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
    debit_id = await _seed_account(
        db_session, "Cash-HTTP", AccountType.ASSET, code="1100"
    )
    credit_id = await _seed_account(
        db_session, "Revenue-HTTP", AccountType.REVENUE, code="4000"
    )

    payload = {
        "description": "Unbalanced via HTTP",
        "transaction_date": "2024-01-01",
        # "amount" removed from transaction level
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": 1000,
                "currency": "EUR",
            },
            {
                "account_id": credit_id,
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
    debit_id = await _seed_account(
        db_session, "Cash-201", AccountType.ASSET, code="1101"
    )
    credit_id = await _seed_account(
        db_session, "Revenue-201", AccountType.REVENUE, code="4001"
    )

    payload = {
        "description": "Sales receipt",
        "transaction_date": "2024-06-01",
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": 5000,
                "currency": "EUR",
            },
            {
                "account_id": credit_id,
                "direction": "credit",
                "amount": 5000,
                "currency": "EUR",
            },
        ],
    }

    response = await async_client.post("/api/v1/transactions", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    assert body["description"] == "Sales receipt"
    assert len(body["entries"]) == 2
    assert body["status"] == "posted"
    assert "amount" not in body


@pytest.mark.asyncio
async def test_get_transactions_returns_list_shape(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    debit_id = await _seed_account(
        db_session, "Cash-GET", AccountType.ASSET, code="1102"
    )
    credit_id = await _seed_account(
        db_session, "Revenue-GET", AccountType.REVENUE, code="4002"
    )

    post_payload = {
        "description": "GET shape check",
        "transaction_date": "2024-06-02",
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": 300,
                "currency": "EUR",
            },
            {
                "account_id": credit_id,
                "direction": "credit",
                "amount": 300,
                "currency": "EUR",
            },
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
async def test_list_transactions_default_limit_returns_at_most_20(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /transactions without params must default to limit=20 (TD-003)."""
    debit_id = await _seed_account(
        db_session, "Cash-Limit", AccountType.ASSET, code="1110"
    )
    credit_id = await _seed_account(
        db_session, "Revenue-Limit", AccountType.REVENUE, code="4010"
    )
    payload_base = {
        "transaction_date": "2024-01-01",
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": 10,
                "currency": "EUR",
            },
            {
                "account_id": credit_id,
                "direction": "credit",
                "amount": 10,
                "currency": "EUR",
            },
        ],
    }
    for i in range(25):
        await async_client.post(
            "/api/v1/transactions", json={**payload_base, "description": f"tx-{i}"}
        )

    response = await async_client.get("/api/v1/transactions")
    assert response.status_code == 200
    assert len(response.json()) <= 20


@pytest.mark.asyncio
async def test_list_transactions_offset_skips_records(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /transactions?limit=1&offset=0 and offset=1 must return different records (TD-003)."""
    debit_id = await _seed_account(
        db_session, "Cash-Off", AccountType.ASSET, code="1111"
    )
    credit_id = await _seed_account(
        db_session, "Revenue-Off", AccountType.REVENUE, code="4011"
    )
    payload_base = {
        "transaction_date": "2024-01-01",
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": 10,
                "currency": "EUR",
            },
            {
                "account_id": credit_id,
                "direction": "credit",
                "amount": 10,
                "currency": "EUR",
            },
        ],
    }
    for i in range(2):
        await async_client.post(
            "/api/v1/transactions",
            json={**payload_base, "description": f"offset-tx-{i}"},
        )

    r0 = await async_client.get(
        "/api/v1/transactions", params={"limit": 1, "offset": 0}
    )
    r1 = await async_client.get(
        "/api/v1/transactions", params={"limit": 1, "offset": 1}
    )
    assert r0.status_code == 200
    assert r1.status_code == 200
    assert r0.json()[0]["id"] != r1.json()[0]["id"]


@pytest.mark.asyncio
async def test_post_then_get_shows_persisted_record(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    debit_id = await _seed_account(
        db_session, "Cash-Persist", AccountType.ASSET, code="1103"
    )
    credit_id = await _seed_account(
        db_session, "Revenue-Persist", AccountType.REVENUE, code="4003"
    )

    post_payload = {
        "description": "Persistence test",
        "transaction_date": "2024-06-03",
        "entries": [
            {
                "account_id": debit_id,
                "direction": "debit",
                "amount": 1200,
                "currency": "EUR",
            },
            {
                "account_id": credit_id,
                "direction": "credit",
                "amount": 1200,
                "currency": "EUR",
            },
        ],
    }

    post_resp = await async_client.post("/api/v1/transactions", json=post_payload)
    assert post_resp.status_code == 201
    created_id = post_resp.json()["id"]

    get_resp = await async_client.get("/api/v1/transactions")
    assert get_resp.status_code == 200
    ids_in_list = [item["id"] for item in get_resp.json()]
    assert created_id in ids_in_list


@pytest.mark.asyncio
async def test_list_transactions_ordered_by_transaction_date_desc(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /transactions must be ordered by transaction_date desc (TD-025)."""
    debit_id = await _seed_account(
        db_session, "Cash-Order", AccountType.ASSET, code="1120"
    )
    credit_id = await _seed_account(
        db_session, "Revenue-Order", AccountType.REVENUE, code="4020"
    )

    def _payload(tx_date: str, description: str) -> dict:
        return {
            "description": description,
            "transaction_date": tx_date,
            "entries": [
                {
                    "account_id": debit_id,
                    "direction": "debit",
                    "amount": 10,
                    "currency": "EUR",
                },
                {
                    "account_id": credit_id,
                    "direction": "credit",
                    "amount": 10,
                    "currency": "EUR",
                },
            ],
        }

    for tx_date, description in [
        ("2024-01-01", "oldest"),
        ("2024-03-01", "newest"),
        ("2024-02-01", "middle"),
    ]:
        resp = await async_client.post(
            "/api/v1/transactions", json=_payload(tx_date, description)
        )
        assert resp.status_code == 201

    response = await async_client.get("/api/v1/transactions")
    assert response.status_code == 200
    dates = [item["transaction_date"] for item in response.json()]

    assert dates == ["2024-03-01", "2024-02-01", "2024-01-01"]


@pytest.mark.asyncio
async def test_same_date_transactions_ordered_by_posted_at_desc(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Same-date transactions must be ordered by posted_at DESC (newest first).

    Why this test: transaction_date alone does not break ties when multiple
    transactions share the same date. posted_at (set to datetime.now(UTC) at
    write time) is the secondary sort key. Without this test, a regression
    from .desc() to .asc() on posted_at would go undetected.
    Inserts three transactions sequentially (each POST is awaited) so
    posted_at is monotonically increasing: first < second < third.
    Expected display order: third, second, first.
    """
    debit_id = await _seed_account(
        db_session, "Cash-PostedAt", AccountType.ASSET, code="1130"
    )
    credit_id = await _seed_account(
        db_session, "Revenue-PostedAt", AccountType.REVENUE, code="4030"
    )

    entries = [
        {"account_id": debit_id, "direction": "debit", "amount": 10, "currency": "EUR"},
        {"account_id": credit_id, "direction": "credit", "amount": 10, "currency": "EUR"},
    ]
    # All share the same transaction_date — only posted_at distinguishes them.
    # Sequential awaits guarantee posted_at: first < second < third.
    for description in ["first", "second", "third"]:
        r = await async_client.post(
            "/api/v1/transactions",
            json={"transaction_date": "2024-06-01", "description": description, "entries": entries},
        )
        assert r.status_code == 201

    response = await async_client.get("/api/v1/transactions")
    assert response.status_code == 200
    descriptions = [item["description"] for item in response.json()]
    assert descriptions == ["third", "second", "first"]
