"""Idempotency-Key middleware implemented as a FastAPI dependency.

💡 Design note:
    We use Redis SET NX (set if not exists) with an EX (expiry) so that:
    - First request  → key is stored; processing continues normally.
    - Second request → key already exists; 409 Conflict is raised immediately.
    This avoids duplicate DB writes without adding any DB schema changes.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException, status

from app.core.config import settings

# TTL for idempotency keys in Redis (24 hours)
_IDEMPOTENCY_TTL_SECONDS = 86_400
_REDIS_KEY_PREFIX = "idempotency:"


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """Yield a Redis client. Called once per request."""
    # redis.asyncio handles connection pooling automatically.
    client: aioredis.Redis = aioredis.from_url(
        settings.redis_url, encoding="utf-8", decode_responses=True
    )
    try:
        yield client
    finally:
        await client.aclose()


RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]


async def check_idempotency(
    redis: RedisDep,
    idempotency_key: Annotated[uuid.UUID | None, Header()] = None,
) -> AsyncGenerator[None, None]:
    """FastAPI dependency: reject duplicate requests by Idempotency-Key.

    - If the header is absent, skip the check (key is optional).
    - If the key is new   → store it in Redis (NX + EX) and continue.
    - If the key exists   → raise 409 Conflict.
    - If the request fails (any exception) → delete the key so the client can retry.
      Prevents legitimate retries from being permanently blocked by a failed request
      that set the key before the DB transaction committed (TD-017).
    """
    if idempotency_key is None:
        yield
        return

    redis_key = f"{_REDIS_KEY_PREFIX}{idempotency_key}"

    was_set = await redis.set(redis_key, "1", nx=True, ex=_IDEMPOTENCY_TTL_SECONDS)
    if not was_set:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate request: Idempotency-Key already used",
        )
    try:
        yield
    except Exception:
        # TODO: implement (hint: await redis.delete(redis_key) to release the key)
        raise


IdempotencyDep = Annotated[None, Depends(check_idempotency)]
