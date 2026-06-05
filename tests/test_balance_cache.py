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
    # 🔧 Fill-in: verify that a cache miss queries the DB and stores the result in Redis
    # TODO: step 1 — POST /api/v1/accounts to create cash (asset) and revenue accounts
    # TODO: step 2 — POST /api/v1/transactions (debit cash 1000, credit revenue 1000)
    # TODO: step 3 — GET /api/v1/accounts/{cash_id}/balance?as_of=2026-01-31T00:00:00
    # TODO: step 4 — assert response status 200 and balance == 1000
    # TODO: step 5 — assert await redis_client.get(f"balance:{cash_id}:2026-01-31") == "1000"
    pass


@pytest.mark.asyncio
async def test_balance_cache_hit_returns_cached_value(
    cached_client: AsyncClient,
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
) -> None:
    # 🔧 Fill-in: verify that a pre-seeded Redis value is returned without hitting the DB
    # TODO: step 1 — POST /api/v1/accounts to create a cash account (no transactions)
    # TODO: step 2 — directly seed Redis: await redis_client.set(f"balance:{cash_id}:2026-01-31", "9999", ex=60)
    # TODO: step 3 — GET /api/v1/accounts/{cash_id}/balance?as_of=2026-01-31T00:00:00
    # TODO: step 4 — assert balance == 9999 (proves cache hit; DB has no transactions so would return 0)
    pass


@pytest.mark.asyncio
async def test_post_transaction_invalidates_balance_cache(
    cached_client: AsyncClient,
    redis_client: aioredis.Redis,  # type: ignore[type-arg]
) -> None:
    # 🔧 Fill-in: verify that POST /transactions deletes the balance cache key
    # TODO: step 1 — POST /api/v1/accounts to create cash and revenue accounts
    # TODO: step 2 — GET /api/v1/accounts/{cash_id}/balance to populate the cache
    # TODO: step 3 — assert the cache key now exists in Redis
    # TODO: step 4 — POST /api/v1/transactions (debit cash, credit revenue)
    # TODO: step 5 — assert await redis_client.get(f"balance:{cash_id}:...") is None
    pass
