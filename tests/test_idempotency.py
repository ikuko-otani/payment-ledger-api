"""Tests for Idempotency-Key middleware on POST /transactions."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.models.account import AccountType


@pytest_asyncio.fixture()
async def idempotent_client(async_client: AsyncClient) -> AsyncClient:
    # async_client already overrides get_redis_client (app.core.redis),
    # which covers both balance-cache and idempotency deps after TD-020.
    yield async_client


@pytest_asyncio.fixture()
async def full_flow_client(async_client: AsyncClient) -> AsyncClient:
    # Same as idempotent_client: single override in async_client covers both deps.
    yield async_client


async def test_same_idempotency_key_replays_200_on_second_request(
    idempotent_client: AsyncClient,
    db_session,
) -> None:
    """Duplicate request with the same key returns 200 + the original response body (Stripe-style)."""
    from tests.test_transactions import _create_account as create_account

    acc_debit = await create_account(
        db_session, name="Cash", account_type=AccountType.ASSET, code="1100"
    )
    acc_credit = await create_account(
        db_session, name="Revenue", account_type=AccountType.REVENUE, code="4000"
    )

    key = str(uuid.uuid4())
    payload = {
        "description": "Idempotency test",
        "transaction_date": "2024-06-01",
        "entries": [
            {
                "account_id": str(acc_debit.id),
                "direction": "debit",
                "amount": 100,
                "currency": "EUR",
            },
            {
                "account_id": str(acc_credit.id),
                "direction": "credit",
                "amount": 100,
                "currency": "EUR",
            },
        ],
    }
    headers = {"Idempotency-Key": key}

    r1 = await idempotent_client.post(
        "/api/v1/transactions", json=payload, headers=headers
    )
    assert r1.status_code == 201

    r2 = await idempotent_client.post(
        "/api/v1/transactions", json=payload, headers=headers
    )
    assert r2.status_code == 200
    assert r2.json() == r1.json()


async def test_different_idempotency_keys_both_succeed(
    idempotent_client: AsyncClient,
    db_session,
) -> None:
    from tests.test_transactions import _create_account as create_account

    acc_debit = await create_account(
        db_session, name="Cash2", account_type=AccountType.ASSET, code="1101"
    )
    acc_credit = await create_account(
        db_session, name="Revenue2", account_type=AccountType.REVENUE, code="4001"
    )

    payload = {
        "description": "Different keys test",
        "transaction_date": "2024-06-01",
        "entries": [
            {
                "account_id": str(acc_debit.id),
                "direction": "debit",
                "amount": 50,
                "currency": "EUR",
            },
            {
                "account_id": str(acc_credit.id),
                "direction": "credit",
                "amount": 50,
                "currency": "EUR",
            },
        ],
    }

    r1 = await idempotent_client.post(
        "/api/v1/transactions",
        json=payload,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    r2 = await idempotent_client.post(
        "/api/v1/transactions",
        json=payload,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert r1.status_code == 201
    assert r2.status_code == 201


@pytest.mark.asyncio
async def test_idempotency_key_arbitrary_string_returns_422(
    idempotent_client: AsyncClient,
) -> None:
    response = await idempotent_client.post(
        "/api/v1/transactions", json={}, headers={"Idempotency-Key": "not-a-uuid"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_idempotency_key_numeric_string_returns_422(
    idempotent_client: AsyncClient,
) -> None:
    response = await idempotent_client.post(
        "/api/v1/transactions", json={}, headers={"Idempotency-Key": "12345"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_failed_transaction_releases_idempotency_key_for_retry(
    idempotent_client: AsyncClient,
    db_session,
) -> None:
    """[H-1] Key must be deleted when the request fails so the client can retry (TD-017)."""
    from tests.test_transactions import _create_account as create_account

    acc_debit = await create_account(
        db_session,
        name="Cash4",
        account_type=AccountType.ASSET,
        code="1103",
        currency="USD",
    )
    acc_credit = await create_account(
        db_session,
        name="Revenue4",
        account_type=AccountType.REVENUE,
        code="4003",
        currency="USD",
    )
    key = str(uuid.uuid4())

    bad_payload = {
        "description": "Unbalanced",
        "transaction_date": "2024-06-01",
        "entries": [
            {
                "account_id": str(acc_debit.id),
                "direction": "debit",
                "amount": 200,
                "currency": "USD",
            },
            {
                "account_id": str(acc_credit.id),
                "direction": "credit",
                "amount": 100,
                "currency": "USD",
            },
        ],
    }
    r1 = await idempotent_client.post(
        "/api/v1/transactions", json=bad_payload, headers={"Idempotency-Key": key}
    )
    assert r1.status_code == 422

    good_payload = {
        "description": "Retry after fix",
        "transaction_date": "2024-06-01",
        "entries": [
            {
                "account_id": str(acc_debit.id),
                "direction": "debit",
                "amount": 100,
                "currency": "USD",
            },
            {
                "account_id": str(acc_credit.id),
                "direction": "credit",
                "amount": 100,
                "currency": "USD",
            },
        ],
    }
    r2 = await idempotent_client.post(
        "/api/v1/transactions", json=good_payload, headers={"Idempotency-Key": key}
    )
    assert r2.status_code == 201


@pytest.mark.asyncio
async def test_balance_reflects_new_transaction_after_commit(
    full_flow_client: AsyncClient,
    db_session,
) -> None:
    """[H-2] Balance endpoint must return updated balance after a transaction is posted (TD-018)."""
    from datetime import datetime

    from tests.test_transactions import _create_account as create_account

    acc_debit = await create_account(
        db_session,
        name="Cash5",
        account_type=AccountType.ASSET,
        code="1104",
        currency="USD",
    )
    acc_credit = await create_account(
        db_session,
        name="Revenue5",
        account_type=AccountType.REVENUE,
        code="4004",
        currency="USD",
    )

    payload = {
        "description": "Balance commit test",
        "transaction_date": "2024-06-01",
        "entries": [
            {
                "account_id": str(acc_debit.id),
                "direction": "debit",
                "amount": 500,
                "currency": "USD",
            },
            {
                "account_id": str(acc_credit.id),
                "direction": "credit",
                "amount": 500,
                "currency": "USD",
            },
        ],
    }
    r_post = await full_flow_client.post("/api/v1/transactions", json=payload)
    assert r_post.status_code == 201

    as_of = datetime.utcnow().isoformat()
    r_balance = await full_flow_client.get(
        f"/api/v1/accounts/{acc_debit.id}/balance", params={"as_of": as_of}
    )
    assert r_balance.status_code == 200
    assert r_balance.json()["balance"] == 500


async def test_no_idempotency_key_header_succeeds(
    idempotent_client: AsyncClient,
    db_session,
) -> None:
    from tests.test_transactions import _create_account as create_account

    acc_debit = await create_account(
        db_session, name="Cash3", account_type=AccountType.ASSET, code="1102"
    )
    acc_credit = await create_account(
        db_session, name="Revenue3", account_type=AccountType.REVENUE, code="4002"
    )

    payload = {
        "description": "No key test",
        "transaction_date": "2024-06-01",
        "entries": [
            {
                "account_id": str(acc_debit.id),
                "direction": "debit",
                "amount": 30,
                "currency": "EUR",
            },
            {
                "account_id": str(acc_credit.id),
                "direction": "credit",
                "amount": 30,
                "currency": "EUR",
            },
        ],
    }
    r = await idempotent_client.post("/api/v1/transactions", json=payload)
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_same_key_different_body_returns_422(
    idempotent_client: AsyncClient,
    db_session,
) -> None:
    """Same idempotency key with a different request body must return 422 (TD-041)."""
    from tests.test_transactions import _create_account as create_account

    acc_debit = await create_account(
        db_session, name="Cash6", account_type=AccountType.ASSET, code="1105"
    )
    acc_credit = await create_account(
        db_session, name="Revenue6", account_type=AccountType.REVENUE, code="4005"
    )

    key = str(uuid.uuid4())
    headers = {"Idempotency-Key": key}

    payload_1 = {
        "description": "First payload",
        "transaction_date": "2024-06-01",
        "entries": [
            {
                "account_id": str(acc_debit.id),
                "direction": "debit",
                "amount": 100,
                "currency": "EUR",
            },
            {
                "account_id": str(acc_credit.id),
                "direction": "credit",
                "amount": 100,
                "currency": "EUR",
            },
        ],
    }
    payload_2 = {
        "description": "Different payload",
        "transaction_date": "2024-06-01",
        "entries": [
            {
                "account_id": str(acc_debit.id),
                "direction": "debit",
                "amount": 200,
                "currency": "EUR",
            },
            {
                "account_id": str(acc_credit.id),
                "direction": "credit",
                "amount": 200,
                "currency": "EUR",
            },
        ],
    }

    r1 = await idempotent_client.post(
        "/api/v1/transactions", json=payload_1, headers=headers
    )
    assert r1.status_code == 201

    r2 = await idempotent_client.post(
        "/api/v1/transactions", json=payload_2, headers=headers
    )
    assert r2.status_code == 422
    assert "different request body" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_concurrent_inflight_idempotency_returns_409(
    idempotent_client: AsyncClient,
    db_session,
) -> None:
    """TD-045: two concurrent requests with the same idempotency key —
    the second hits the 'pending' branch (no cached response yet) and
    receives 409.
    """
    import asyncio

    from tests.test_transactions import _create_account as create_account

    acc_debit = await create_account(
        db_session, name="Cash7", account_type=AccountType.ASSET, code="1106"
    )
    acc_credit = await create_account(
        db_session, name="Revenue7", account_type=AccountType.REVENUE, code="4006"
    )

    shared_key = str(uuid.uuid4())
    payload = {
        "description": "Concurrent inflight test",
        "transaction_date": "2024-06-01",
        "entries": [
            {
                "account_id": str(acc_debit.id),
                "direction": "debit",
                "amount": 300,
                "currency": "EUR",
            },
            {
                "account_id": str(acc_credit.id),
                "direction": "credit",
                "amount": 300,
                "currency": "EUR",
            },
        ],
    }
    headers = {"Idempotency-Key": shared_key}

    async def _post() -> int:
        r = await idempotent_client.post(
            "/api/v1/transactions", json=payload, headers=headers
        )
        return r.status_code

    status_codes = sorted(await asyncio.gather(_post(), _post()))

    assert status_codes == [201, 409], f"Expected [201, 409], got {status_codes}"
