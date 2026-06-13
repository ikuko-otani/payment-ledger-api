"""Tests for Idempotency-Key middleware on POST /transactions."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import AsyncClient
from testcontainers.redis import RedisContainer

from app.core.cache import get_redis_client
from app.dependencies.idempotency import get_redis
from app.main import app as fastapi_app
from app.models.account import AccountType

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# redis_container is defined in conftest.py (session-scoped, shared across all test files)


@pytest_asyncio.fixture()
async def redis_client(redis_container: RedisContainer):
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    client: aioredis.Redis = aioredis.from_url(  # type: ignore[type-arg]
        f"redis://{host}:{port}", encoding="utf-8", decode_responses=True
    )
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture()
async def idempotent_client(
    async_client: AsyncClient,
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
):
    async def override_get_redis():
        yield redis_client

    fastapi_app.dependency_overrides[get_redis] = override_get_redis
    yield async_client


@pytest_asyncio.fixture()
async def full_flow_client(
    async_client: AsyncClient,
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
):
    """Override both Redis dependencies (idempotency + balance cache) with the test container."""

    async def override_get_redis():
        yield redis_client

    async def override_get_redis_client():
        yield redis_client

    fastapi_app.dependency_overrides[get_redis] = override_get_redis
    fastapi_app.dependency_overrides[get_redis_client] = override_get_redis_client
    yield async_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_same_idempotency_key_returns_409_on_second_request(
    idempotent_client: AsyncClient,
    async_client: AsyncClient,
    db_session,
) -> None:
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
        # "amount" removed from transaction level
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
    print(r1.json())
    assert r1.status_code == 201

    r2 = await idempotent_client.post(
        "/api/v1/transactions", json=payload, headers=headers
    )
    assert r2.status_code == 409
    assert "Idempotency-Key" in r2.json()["detail"]


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

    # Step 1: Send an unbalanced transaction — should return 422
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

    # Step 2: Retry with the same key and a valid payload — key should have been released
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

    # Step 1: POST a transaction (debit 500 against acc_debit)
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

    # Step 2: GET balance for acc_debit — should reflect the posted debit
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
