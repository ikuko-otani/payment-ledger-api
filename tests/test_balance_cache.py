"""Tests for GET /accounts/{id}/balance Redis Cache-Aside behavior."""

from __future__ import annotations

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import AsyncClient
from testcontainers.redis import RedisContainer

from app.core.cache import get_redis_client
from app.main import app as fastapi_app

# redis_container is defined in conftest.py (session-scoped, shared across all test files)


@pytest_asyncio.fixture()
async def redis_client(redis_container: RedisContainer) -> aioredis.Redis:  # type: ignore[type-arg]
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    client: aioredis.Redis = aioredis.from_url(  # type: ignore[type-arg]
        f"redis://{host}:{port}", encoding="utf-8", decode_responses=True
    )
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture()
async def cached_client(
    async_client: AsyncClient,
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
) -> AsyncClient:
    async def override_get_redis_client():
        yield redis_client

    fastapi_app.dependency_overrides[get_redis_client] = override_get_redis_client
    yield async_client
    # dependency_overrides.clear() is handled by async_client fixture teardown


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_balance_cache_miss_stores_value_in_redis(
    cached_client: AsyncClient,
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
) -> None:
    resp = await cached_client.post(
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

    resp = await cached_client.post(
        "/api/v1/accounts",
        json={
            "code": "4001",
            "name": "Revenue",
            "account_type": "revenue",
            "currency": "EUR",
        },
    )
    assert resp.status_code == 201
    revenue_id = resp.json()["id"]

    await cached_client.post(
        "/api/v1/transactions",
        json={
            "description": "cache miss test",
            "transaction_date": "2026-01-10",
            "entries": [
                {
                    "account_id": cash_id,
                    "direction": "debit",
                    "amount": 1000,
                    "currency": "EUR",
                },
                {
                    "account_id": revenue_id,
                    "direction": "credit",
                    "amount": 1000,
                    "currency": "EUR",
                },
            ],
        },
    )

    resp = await cached_client.get(
        f"/api/v1/accounts/{cash_id}/balance",
        params={"as_of": "2026-01-31T00:00:00"},
    )
    assert resp.status_code == 200
    assert resp.json()["balance"] == 1000

    cached = await redis_client.get(f"balance:{cash_id}:2026-01-31")
    assert cached == "1000"


@pytest.mark.asyncio
async def test_balance_cache_hit_returns_cached_value(
    cached_client: AsyncClient,
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
) -> None:
    resp = await cached_client.post(
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

    await redis_client.set(f"balance:{cash_id}:2026-01-31", "9999", ex=60)

    resp = await cached_client.get(
        f"/api/v1/accounts/{cash_id}/balance",
        params={"as_of": "2026-01-31T00:00:00"},
    )
    assert resp.status_code == 200
    assert resp.json()["balance"] == 9999


@pytest.mark.asyncio
async def test_post_transaction_invalidates_balance_cache(
    cached_client: AsyncClient,
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
) -> None:
    resp = await cached_client.post(
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

    resp = await cached_client.post(
        "/api/v1/accounts",
        json={
            "code": "4001",
            "name": "Revenue",
            "account_type": "revenue",
            "currency": "EUR",
        },
    )
    assert resp.status_code == 201
    revenue_id = resp.json()["id"]

    await cached_client.get(
        f"/api/v1/accounts/{cash_id}/balance",
        params={"as_of": "2026-01-31T00:00:00"},
    )
    assert await redis_client.get(f"balance:{cash_id}:2026-01-31") is not None

    await cached_client.post(
        "/api/v1/transactions",
        json={
            "description": "invalidation test",
            "transaction_date": "2026-01-10",
            "entries": [
                {
                    "account_id": cash_id,
                    "direction": "debit",
                    "amount": 500,
                    "currency": "EUR",
                },
                {
                    "account_id": revenue_id,
                    "direction": "credit",
                    "amount": 500,
                    "currency": "EUR",
                },
            ],
        },
    )

    assert await redis_client.get(f"balance:{cash_id}:2026-01-31") is None
    assert await redis_client.get(f"balance:{revenue_id}:2026-01-31") is None
