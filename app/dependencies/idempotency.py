"""Idempotency-Key middleware implemented as a FastAPI dependency.

💡 Design note:
    Two-phase Redis state machine with request fingerprinting (TD-041):
    - Phase 1 (new request):   SET NX key {"fingerprint":"sha256","status":"pending"}
    - Phase 2 (on success):    SET key {"fingerprint":"sha256","response":{...}}
    - Duplicate (cached):      GET key → fingerprint match + response present → replay 200.
    - Duplicate (in-flight):   GET key → fingerprint match + status pending → 409.
    - Fingerprint mismatch:    GET key → fingerprint differs → 422.
    - Failed request:          DELETE key → client may retry with the same key.

    Implements Stripe-style idempotency: retrying a successful request returns
    the original response body with 200 instead of 409 Conflict (TD-004/005).
    Request body SHA-256 hash prevents silent request drop when the same key
    is reused with a different payload (TD-041).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import Depends, Header, Request, status
from fastapi.exceptions import HTTPException

from app.core.redis import RedisDep

_IDEMPOTENCY_TTL_SECONDS = 86_400
_REDIS_KEY_PREFIX = "idempotency:"


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
        fingerprint: str = "",
    ) -> None:
        self.replay = replay
        self._redis = redis
        self._redis_key = redis_key
        self._fingerprint = fingerprint

    async def cache(self, response_body: dict[str, Any]) -> None:
        """Overwrite the pending marker with the serialised response body."""
        if self._redis is not None and self._redis_key:
            data = {"fingerprint": self._fingerprint, "response": response_body}
            await self._redis.set(
                self._redis_key,
                json.dumps(data),
                ex=_IDEMPOTENCY_TTL_SECONDS,
            )


async def check_idempotency(
    request: Request,
    redis: RedisDep,
    idempotency_key: Annotated[uuid.UUID | None, Header()] = None,
) -> AsyncGenerator[IdempotencyContext, None]:
    """FastAPI dependency: Stripe-style idempotency with request fingerprinting.

    - Key absent    → yield empty context (no check).
    - Key new       → SET NX pending+fingerprint; yield context with cache() wired up.
    - Key + match   → replay cached response (200) or reject in-flight duplicate (409).
    - Key + mismatch→ 422 (same key reused with different body).
    - Any exception → DELETE key so client can retry.
    """
    if idempotency_key is None:
        yield IdempotencyContext()
        return

    body = await request.body()
    fingerprint = hashlib.sha256(body).hexdigest()
    redis_key = f"{_REDIS_KEY_PREFIX}{idempotency_key}"

    pending_data = json.dumps({"fingerprint": fingerprint, "status": "pending"})
    was_set = await redis.set(
        redis_key, pending_data, nx=True, ex=_IDEMPOTENCY_TTL_SECONDS
    )

    if not was_set:
        raw = await redis.get(redis_key)
        if raw is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Duplicate request: Idempotency-Key already used",
            )
        try:
            stored = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Duplicate request: Idempotency-Key already used",
            ) from None

        stored_fingerprint = stored.get("fingerprint", "")
        if stored_fingerprint != fingerprint:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Idempotency-Key reused with different request body",
            )

        if "response" in stored:
            yield IdempotencyContext(replay=stored["response"])
            return

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate request: Idempotency-Key already used",
        )

    ctx = IdempotencyContext(
        redis=redis,
        redis_key=redis_key,
        fingerprint=fingerprint,
    )
    try:
        yield ctx
    except Exception:
        await redis.delete(redis_key)
        raise


IdempotencyDep = Annotated[IdempotencyContext, Depends(check_idempotency)]
