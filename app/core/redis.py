"""Shared Redis client: created once during app startup (see app.main.lifespan).

TD-020: core/cache.py and dependencies/idempotency.py used to each define
near-duplicate functions, both calling aioredis.from_url() on every request.
Both now depend on get_redis_client defined here, which returns the single
client stored on app.state.redis by the lifespan context manager.
"""

from __future__ import annotations

from typing import Annotated, cast

import redis.asyncio as aioredis
from fastapi import Depends, Request

from app.core.config import settings


def create_redis_client() -> aioredis.Redis:
    """Create the process-lifetime Redis client. Called once from app.main.lifespan."""
    return aioredis.from_url(
        settings.redis_url, encoding="utf-8", decode_responses=True
    )


async def get_redis_client(request: Request) -> aioredis.Redis:
    """Return the lifespan-scoped Redis client shared by all dependencies."""
    return cast(aioredis.Redis, request.app.state.redis)


RedisDep = Annotated[aioredis.Redis, Depends(get_redis_client)]
