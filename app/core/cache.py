"""Redis client dependency for balance cache."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends

from app.core.config import settings


# 🔧 Fill-in: implement the async generator.
#    Hint: follow the same pattern as get_redis() in app/dependencies/idempotency.py
async def get_redis_client() -> AsyncGenerator[aioredis.Redis, None]:  # type: ignore[type-arg]
    # TODO: implement
    # hint 1: client = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    # hint 2: try: yield client
    # hint 3: finally: await client.aclose()
    raise NotImplementedError


RedisDep = Annotated[aioredis.Redis, Depends(get_redis_client)]  # type: ignore[type-arg]
