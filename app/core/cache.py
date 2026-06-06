"""Redis client dependency for balance cache."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends

from app.core.config import settings


async def get_redis_client() -> AsyncGenerator[aioredis.Redis, None]:  # type: ignore[type-arg]
    client: aioredis.Redis = aioredis.from_url(  # type: ignore[type-arg]
        settings.redis_url, encoding="utf-8", decode_responses=True
    )
    try:
        yield client
    finally:
        await client.aclose()


RedisDep = Annotated[aioredis.Redis, Depends(get_redis_client)]  # type: ignore[type-arg]
