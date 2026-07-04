"""Tests for GET /accounts/{id}/balance Redis Cache-Aside behavior."""

from __future__ import annotations

import json
from datetime import date

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import AsyncClient
from testcontainers.redis import RedisContainer

from app.core.config import settings
from app.core.redis import get_redis_client
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
    assert resp.json()["currency"] == "EUR"

    cached = await redis_client.get(f"balance:{cash_id}:2026-01-31")
    assert cached is not None
    data = json.loads(cached)
    assert data == {"balance": 1000, "currency": "EUR"}


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

    await redis_client.set(
        f"balance:{cash_id}:2026-01-31",
        json.dumps({"balance": 9999, "currency": "EUR"}),
        ex=60,
    )

    resp = await cached_client.get(
        f"/api/v1/accounts/{cash_id}/balance",
        params={"as_of": "2026-01-31T00:00:00"},
    )
    assert resp.status_code == 200
    assert resp.json()["balance"] == 9999
    assert resp.json()["currency"] == "EUR"


@pytest.mark.asyncio
async def test_balance_cache_hit_does_not_query_db(
    cached_client: AsyncClient,
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
) -> None:
    """Cache hit returns the cached value without any DB lookup.

    The account does not exist in the database — if the route tried
    find_by_id it would get None and return 404.  A 200 proves the
    cache-hit path is entirely DB-free.
    """
    fake_id = "00000000-0000-4000-a000-000000000099"
    await redis_client.set(
        f"balance:{fake_id}:2026-01-31",
        json.dumps({"balance": 5000, "currency": "JPY"}),
        ex=60,
    )

    resp = await cached_client.get(
        f"/api/v1/accounts/{fake_id}/balance",
        params={"as_of": "2026-01-31T00:00:00"},
    )
    assert resp.status_code == 200
    assert resp.json()["balance"] == 5000
    assert resp.json()["currency"] == "JPY"


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


@pytest.mark.asyncio
async def test_balance_cache_ttl_longer_for_historical_date(
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

    await cached_client.get(
        f"/api/v1/accounts/{cash_id}/balance",
        params={"as_of": "2020-01-01T00:00:00"},
    )

    ttl = await redis_client.ttl(f"balance:{cash_id}:2020-01-01")
    assert ttl > settings.balance_cache_ttl_seconds


@pytest.mark.asyncio
async def test_balance_cache_ttl_short_for_current_date(
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

    today = date.today().isoformat()
    await cached_client.get(
        f"/api/v1/accounts/{cash_id}/balance",
        params={"as_of": f"{today}T00:00:00"},
    )

    ttl = await redis_client.ttl(f"balance:{cash_id}:{today}")
    assert 0 < ttl <= settings.balance_cache_ttl_seconds


@pytest_asyncio.fixture()
async def broken_redis_client() -> aioredis.Redis:  # type: ignore[type-arg]
    """A Redis client pointing at an address with nothing listening, to
    simulate Redis being unreachable. socket_connect_timeout keeps the
    failure fast instead of hanging on OS-level TCP retries.
    """
    client: aioredis.Redis = aioredis.from_url(  # type: ignore[type-arg]
        "redis://localhost:1",
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=1,
    )
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_balance_reads_from_db_when_redis_unavailable(
    async_client: AsyncClient,
    broken_redis_client: aioredis.Redis,  # type: ignore[type-arg]
) -> None:
    """GET /accounts/{id}/balance must still return the correct balance from
    PostgreSQL when Redis is unreachable, not a 500 (N-4 regression guard for
    the try/except added around redis.get/set in get_account_balance).
    """
    resp = await async_client.post(
        "/api/v1/accounts",
        json={
            "code": "1102",
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
            "code": "4002",
            "name": "Revenue",
            "account_type": "revenue",
            "currency": "EUR",
        },
    )
    assert resp.status_code == 201
    revenue_id = resp.json()["id"]

    resp = await async_client.post(
        "/api/v1/transactions",
        json={
            "description": "redis down test",
            "transaction_date": "2026-01-10",
            "entries": [
                {
                    "account_id": cash_id,
                    "direction": "debit",
                    "amount": 1500,
                    "currency": "EUR",
                },
                {
                    "account_id": revenue_id,
                    "direction": "credit",
                    "amount": 1500,
                    "currency": "EUR",
                },
            ],
        },
    )
    assert resp.status_code == 201

    # Only now switch Redis to the broken client — the GET below is the one
    # code path we actually fixed (get_account_balance's try/except).
    async def override_get_redis_client():
        yield broken_redis_client

    fastapi_app.dependency_overrides[get_redis_client] = override_get_redis_client

    resp = await async_client.get(
        f"/api/v1/accounts/{cash_id}/balance",
        params={"as_of": "2026-01-10T00:00:00"},
    )
    assert resp.status_code == 200
    assert resp.json()["balance"] == 1500
    assert resp.json()["currency"] == "EUR"
