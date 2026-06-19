"""Idempotency-Key middleware implemented as a FastAPI dependency.

💡 Design note:
    Two-phase Redis state machine:
    - Phase 1 (new request):   SET NX key "__pending__" → continue processing.
    - Phase 2 (on success):    SET key <response JSON> (overwrites "__pending__").
    - Duplicate (cached):      GET key → JSON found → replay 200.
    - Duplicate (in-flight):   GET key → "__pending__" found → 409.
    - Failed request:          DELETE key → client may retry with the same key.

    Implements Stripe-style idempotency: retrying a successful request returns
    the original response body with 200 instead of 409 Conflict (TD-004/005).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import Depends, Header, HTTPException, status

from app.core.redis import RedisDep

# TTL for idempotency keys in Redis (24 hours)
_IDEMPOTENCY_TTL_SECONDS = 86_400
_REDIS_KEY_PREFIX = "idempotency:"
_PENDING_MARKER = "__pending__"


class IdempotencyContext:
    """Carries idempotency state through the request lifecycle.

    replay:  non-None when a cached response exists; the route handler
             must return JSONResponse(self.replay, status_code=200) immediately.
    cache(): called by the route handler after success to persist the response
             body in Redis so future duplicate requests can replay it.
    """

    def __init__(
        self,
        replay: dict[str, Any] | None = None,
        redis: aioredis.Redis | None = None,
        redis_key: str = "",
    ) -> None:
        self.replay = replay
        self._redis = redis
        self._redis_key = redis_key

    async def cache(self, response_body: dict[str, Any]) -> None:
        """Overwrite the __pending__ marker with the serialised response body."""
        if self._redis is not None and self._redis_key:
            await self._redis.set(
                self._redis_key,
                json.dumps(response_body),
                ex=_IDEMPOTENCY_TTL_SECONDS,
            )


async def check_idempotency(
    redis: RedisDep,
    idempotency_key: Annotated[uuid.UUID | None, Header()] = None,
) -> AsyncGenerator[IdempotencyContext, None]:
    """FastAPI dependency: Stripe-style idempotency via two-phase Redis state machine.

    - Key absent    → yield empty context (no check).
    - Key new       → SET NX "__pending__"; yield context with cache() wired up.
    - Key = JSON    → yield context with replay populated; route handler returns early.
    - Key = pending → 409 (in-flight duplicate or race).
    - Any exception → DELETE key so client can retry.
    """
    if idempotency_key is None:
        yield IdempotencyContext()
        return

    redis_key = f"{_REDIS_KEY_PREFIX}{idempotency_key}"

    # Atomically claim the key. Returns True only if the key did not exist.
    was_set = await redis.set(
        redis_key, _PENDING_MARKER, nx=True, ex=_IDEMPOTENCY_TTL_SECONDS
    )

    if not was_set:
        # Key exists — check whether it holds a cached response or a pending marker.
        raw = await redis.get(redis_key)
        if raw is None:
            # Expired between SET NX and GET (extremely rare with 24h TTL).
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Duplicate request: Idempotency-Key already used",
            )
        try:
            cached = json.loads(raw)
            # Valid JSON → original request succeeded; replay the cached body.
            yield IdempotencyContext(replay=cached)
            return
        except json.JSONDecodeError:
            # Still "__pending__": a concurrent duplicate or stale marker.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Duplicate request: Idempotency-Key already used",
            ) from None

    # New request: key is now "__pending__"; wire up cache() for the route handler.
    ctx = IdempotencyContext(redis=redis, redis_key=redis_key)
    try:
        yield ctx
    except Exception:
        # Request failed — remove key so the client can safely retry.
        await redis.delete(redis_key)
        raise


IdempotencyDep = Annotated[IdempotencyContext, Depends(check_idempotency)]
