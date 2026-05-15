"""Tests for Idempotency-Key middleware on POST /transactions."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import AsyncClient
from testcontainers.redis import RedisContainer

from app.dependencies.idempotency import get_redis
from app.main import app as fastapi_app

from app.models.account import AccountType

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("redis:7-alpine") as rc:
        yield rc


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
                "direction": "debit",   # ✍️ renamed from entry_type
                "amount": 100,          # ✍️ int minor units (was "100.00")
                "currency": "EUR",      # ✍️ new required field
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
