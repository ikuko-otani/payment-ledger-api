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
    """Start one Redis container for the whole test session."""
    with RedisContainer("redis:7-alpine") as rc:
        yield rc


@pytest_asyncio.fixture()
async def redis_client(redis_container: RedisContainer):
    """Yield a Redis client connected to the test container."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    client: aioredis.Redis = aioredis.from_url(  # type: ignore[type-arg]
        f"redis://{host}:{port}", encoding="utf-8", decode_responses=True
    )
    yield client
    await client.flushdb()  # clean up keys after each test
    await client.aclose()


@pytest_asyncio.fixture()
async def idempotent_client(
    async_client: AsyncClient,
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
):
    """Override get_redis so the app uses the test Redis container."""

    async def override_get_redis():
        yield redis_client

    fastapi_app.dependency_overrides[get_redis] = override_get_redis
    yield async_client
    # dependency_overrides is cleared by async_client fixture teardown


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

MINIMAL_PAYLOAD = {
    "description": "Idempotency test",
    "transaction_date": "2024-06-01",
    "entries": [
        {"account_id": None, "amount": "100.00", "entry_type": "debit"},
        {"account_id": None, "amount": "100.00", "entry_type": "credit"},
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_same_idempotency_key_returns_409_on_second_request(
    idempotent_client: AsyncClient,
    async_client: AsyncClient,
    db_session,
) -> None:
    """Second POST with the same Idempotency-Key must return 409 Conflict."""
    from tests.test_transactions import (
        _create_account as create_account,
    )  # reuse account factory

    acc_debit = await create_account(
        db_session, name="Cash", account_type=AccountType.ASSET
    )
    acc_credit = await create_account(
        db_session, name="Revenue", account_type=AccountType.REVENUE
    )

    key = str(uuid.uuid4())
    payload = {
        "description": "Idempotency test",
        "transaction_date": "2024-06-01",
        "amount": "100.00",
        "entries": [
            {
                "account_id": str(acc_debit.id),
                "amount": "100.00",
                "entry_type": "debit",
            },
            {
                "account_id": str(acc_credit.id),
                "amount": "100.00",
                "entry_type": "credit",
            },
        ],
    }
    headers = {"Idempotency-Key": key}

    # First request — should succeed
    r1 = await idempotent_client.post(
        "/api/v1/transactions", json=payload, headers=headers
    )
    print(r1.json())
    assert r1.status_code == 201

    # Send the same payload with the same key again.
    # Assert that the second response has status_code == 409.
    r2 = await idempotent_client.post(
        "/api/v1/transactions", json=payload, headers=headers
    )
    assert r2.status_code == 409
    assert "Idempotency-Key" in r2.json()["detail"]


async def test_different_idempotency_keys_both_succeed(
    idempotent_client: AsyncClient,
    db_session,
) -> None:
    """Two requests with different Idempotency-Keys must both return 201."""
    from tests.test_transactions import _create_account as create_account

    acc_debit = await create_account(
        db_session, name="Cash2", account_type=AccountType.ASSET
    )
    acc_credit = await create_account(
        db_session, name="Revenue2", account_type=AccountType.REVENUE
    )

    payload = {
        "description": "Different keys test",
        "transaction_date": "2024-06-01",
        "amount": "50.00",
        "entries": [
            {"account_id": str(acc_debit.id), "amount": "50.00", "entry_type": "debit"},
            {
                "account_id": str(acc_credit.id),
                "amount": "50.00",
                "entry_type": "credit",
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


async def test_no_idempotency_key_header_succeeds(
    idempotent_client: AsyncClient,
    db_session,
) -> None:
    """Requests without Idempotency-Key header are processed normally."""
    from tests.test_transactions import _create_account as create_account

    acc_debit = await create_account(
        db_session, name="Cash3", account_type=AccountType.ASSET
    )
    acc_credit = await create_account(
        db_session, name="Revenue3", account_type=AccountType.REVENUE
    )

    payload = {
        "description": "No key test",
        "transaction_date": "2024-06-01",
        "amount": "30.00",
        "entries": [
            {"account_id": str(acc_debit.id), "amount": "30.00", "entry_type": "debit"},
            {
                "account_id": str(acc_credit.id),
                "amount": "30.00",
                "entry_type": "credit",
            },
        ],
    }
    r = await idempotent_client.post("/api/v1/transactions", json=payload)
    assert r.status_code == 201
