# S7-4: Lifespan-Scoped Redis Client + Latency Measurement (TD-020/TD-015)

> Date: 2026-06-16
> Branch: `feature/s7-4-redis-lifespan-client`
> PR: #73 (merged)

## Goal

Two related items resolved in a single goal:

- **TD-020**: `core/cache.py:get_redis_client` and
  `dependencies/idempotency.py:get_redis` were near-duplicate functions that
  both called `aioredis.from_url()` on every request — each request created
  and tore down a `ConnectionPool`, discarding all pooling benefits.
- **TD-015**: Measure cache-hit latency before and after the TD-020 fix to
  confirm improvement and document the remaining bottleneck.

DONE conditions:

1. Single Redis client created in lifespan, stored on `app.state`.
2. All Redis dependencies (balance-cache, idempotency) share the same client.
3. Cache-hit latency measured before and after; numbers recorded in
   `docs/tech-debt.md`.
4. All existing tests green (117 passed).

---

## Background: Approach A vs Approach B

The first design question was how to centralise the Redis client without
breaking the existing import paths in `accounts.py`, `transactions.py`, and
`idempotency.py`.

**Approach A (re-export hub)**: keep `app/core/cache.py`, replace its body
with `from app.core.redis import ...`, so existing imports stay unchanged.
Minimises diff size but leaves a misleading module alive purely as an
indirection layer — a future reader would have to chase two hops to reach the
actual implementation.

**Approach B (direct imports, delete cache.py)**: update every consumer to
`from app.core.redis import RedisDep` directly; delete `app/core/cache.py`.
More diff, but the result is honest — every file says exactly where its
dependency comes from. Chosen because design clarity beats diff size in a
small internal portfolio project.

💡 With Approach B, `dependency_overrides[get_redis_client]` in test fixtures
covers **both** balance-cache and idempotency deps automatically, because both
now reference the same function object from `app.core.redis`. This is a
concrete benefit of direct imports over re-export hubs: there is only one
canonical object to override.

---

## Step C-1: Create `app/core/redis.py` + wire lifespan

**`app/core/redis.py`** (new file):

```python
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
    return cast(
        aioredis.Redis,
        aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True),
    )


async def get_redis_client(request: Request) -> aioredis.Redis:
    """Return the lifespan-scoped Redis client shared by all dependencies."""
    return cast(aioredis.Redis, request.app.state.redis)


RedisDep = Annotated[aioredis.Redis, Depends(get_redis_client)]
```

⚠️ `cast` is required in both functions for `mypy --strict`:
- `aioredis.from_url()` returns `Any` in the redis-py type stubs.
- `request.app.state` is Starlette's `State` object, which uses `__getattr__`
  — attribute access is dynamically typed and returns `Any`.

**`app/main.py`** — extended lifespan:

```python
from app.core.redis import create_redis_client

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_structlog()
    configure_telemetry()
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    app.state.redis = create_redis_client()
    try:
        yield
    finally:
        await app.state.redis.aclose()
```

`create_redis_client()` is called **once** at startup; `aclose()` is called
in `finally` so the connection pool is released cleanly on shutdown even if
startup raised an exception after the client was assigned.

⏱ ~20min

✅ Verification:
```bash
uv run mypy app/ --strict
```

```bash
git add app/core/redis.py app/main.py
git commit -m "feat(s7-4): add lifespan-scoped redis client module (TD-020)"
```

---

## Step C-2: Migrate all consumers + delete cache.py

Three consumers updated to `from app.core.redis import RedisDep`:

- `app/dependencies/idempotency.py` — removed local `get_redis()` and `RedisDep`
- `app/api/v1/routes/accounts.py` — `from app.core.cache import RedisDep` → `from app.core.redis import RedisDep`
- `app/api/v1/routes/transactions.py` — same

`app/core/cache.py` deleted:
```bash
git rm app/core/cache.py
```

⏱ ~10min

✅ Verification:
```bash
grep -rn "from app.core.cache" app/
# should return nothing
```

```bash
git add app/dependencies/idempotency.py app/api/v1/routes/accounts.py app/api/v1/routes/transactions.py
git commit -m "refactor(s7-4): migrate all consumers to app.core.redis (TD-020)"
```

---

## Step C-3: Update test fixtures

### The ASGITransport / lifespan gap

`httpx.AsyncClient(transport=ASGITransport(...))` does **not** run FastAPI's
`lifespan` context manager. This means `app.state.redis` is never set in
tests. Old code was safe because `aioredis.from_url()` is lazy — the TCP
socket was not opened until the first Redis command was actually issued (which
never happened in tests that only check auth/routing). New `get_redis_client`
immediately accesses `request.app.state.redis`, which raises
`AttributeError: 'State' object has no attribute 'redis'` the moment FastAPI
resolves the dependency.

**Rule**: every fixture that creates an `AsyncClient` via `ASGITransport` must
override `get_redis_client` in `dependency_overrides`.

### `tests/conftest.py` — `async_client` already had the override.

The `unauthed_client` fixture was missing it. Added `redis_container` param
and the standard `_make_redis_override` + `dependency_overrides` pattern:

```python
@pytest_asyncio.fixture()
async def unauthed_client(
    engine: AsyncEngine,
    redis_container: RedisContainer,  # added
) -> AsyncGenerator[AsyncClient, None]:
    ...
    _redis, override_get_redis_client = _make_redis_override(redis_container)
    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_redis_client] = override_get_redis_client
    ...
    await _redis.aclose()
    fastapi_app.dependency_overrides.clear()
```

### `tests/test_idempotency.py` — simplified after TD-020

Before: `idempotent_client` and `full_flow_client` each created their own
`AsyncClient` with a dedicated `redis_client` fixture (separate
`RedisContainer` connection + `flushdb` teardown per test).

After: both fixtures simply yield `async_client`, because `async_client`'s
`dependency_overrides` already covers the single `get_redis_client` from
`app.core.redis` — which is now the only Redis entry point for both
balance-cache and idempotency.

```python
@pytest_asyncio.fixture()
async def idempotent_client(async_client: AsyncClient) -> AsyncClient:
    yield async_client

@pytest_asyncio.fixture()
async def full_flow_client(async_client: AsyncClient) -> AsyncClient:
    yield async_client
```

⚠️ The `clean_db` fixture (`autouse=True`, scope `function`) calls
`TRUNCATE ... CASCADE`, which removes all Redis keys via `async_client`'s
existing `flushdb` call in teardown. Idempotency key isolation is preserved.

### `tests/test_observability_config.py` — replace deleted test + add two new ones

Deleted: `test_get_redis_client_builds_from_settings_and_closes_on_exit`
(tested the old `cache.py` generator pattern — no longer exists).

Added two replacements:

```python
def test_create_redis_client_builds_from_settings() -> None:
    mock_client = AsyncMock()
    with patch(
        "app.core.redis.aioredis.from_url", return_value=mock_client
    ) as mock_from_url:
        client = create_redis_client()

    assert client is mock_client
    mock_from_url.assert_called_once_with(
        settings.redis_url, encoding="utf-8", decode_responses=True
    )


@pytest.mark.asyncio
async def test_get_redis_client_returns_app_state_redis() -> None:
    mock_client = AsyncMock()
    mock_request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(redis=mock_client))
    )
    result = await get_redis_client(mock_request)  # type: ignore[arg-type]
    assert result is mock_client
```

`SimpleNamespace` from the standard library creates a duck-typed fake
`Request` without needing to import or instantiate Starlette's `Request`.
Only the attributes actually accessed by `get_redis_client` need to exist.

⏱ ~25min

✅ Verification:
```bash
uv run pytest -q
# 117 passed
```

```bash
git add tests/conftest.py tests/test_idempotency.py tests/test_balance_cache.py tests/test_observability_config.py
git commit -m "refactor(s7-4): migrate all consumers to app.core.redis (TD-020)"
```

---

## Step C-4: TD-015 latency measurement

Measured before (on main, before applying TD-020 changes) and after (on this
branch with lifespan client).

| | miss | hit 1 | hit 2 | hit 3 | hit avg |
|---|---|---|---|---|---|
| Before TD-020 | 0.567s | 0.144s | 0.088s | 0.140s | ~124ms |
| After TD-020 | 1.482s* | 0.037s | 0.092s | 0.065s | ~65ms |

*cold start immediately after `docker compose restart api` — not a
meaningful comparison to the before-miss.

**~48% improvement on cache-hit latency** from the shared connection pool:
in the old pattern each request got a new `aioredis.Redis` instance → new
`ConnectionPool` → TCP handshake on every Redis command. With the
lifespan-scoped client the pool is established once and reused across all
requests.

**Why miss is 1.482s after restart**: `aioredis.from_url()` is lazy — the
TCP socket to Redis is not opened until the first command is issued, so
restart + first request = cold pool + cold SQLAlchemy pool + Python process
warm-up, all combined. Subsequent requests (including all cache-hits) avoid
this.

**Remaining ~65ms bottleneck**: `get_current_user` in `app/core/deps.py`
re-queries the `users` table on every authenticated request to resolve the
JWT subject into a `User` row. Redis round-trip itself is under 1ms. Fix
candidates: embed role/active-status claims in JWT; short-lived in-process
cache for `get_current_user`.

```bash
git add docs/tech-debt.md
git commit -m "docs(s7-4): record TD-015 before/after latency and resolve TD-020"
```

---

## Key takeaways

- I learned that `ASGITransport` (used by `httpx.AsyncClient` in tests) does
  not run FastAPI's `lifespan` context manager. This means `app.state.redis`
  is never populated in tests. Old lazy-connection code was safe because the
  socket was not opened until a Redis command was issued; new
  `request.app.state.redis` fails immediately on dependency resolution. The
  rule going forward: any fixture creating a test client must override
  `get_redis_client` in `dependency_overrides`.
- I learned that `dependency_overrides` is keyed by **callable object
  identity**, not by name. With Approach B (direct imports, single canonical
  function in `app.core.redis`), a single override entry in `async_client`
  covers both balance-cache and idempotency consumers, because both reference
  the same function object. If Approach A (re-export hub) had been used, the
  re-exported function would be a different object and a second override entry
  would be needed.
- I learned that `Starlette.State` uses `__getattr__` for dynamic attribute
  access, which makes attribute lookups return `Any`. Under `mypy --strict`,
  returning `Any` from a function typed as `-> aioredis.Redis` fails with
  `no-any-return`. The fix is `cast(aioredis.Redis, request.app.state.redis)`.
  The same applies to `aioredis.from_url()`, whose type stubs also return `Any`.
- I learned (through a design discussion) that favouring the smallest diff
  over the rationally superior design is a form of premature pessimism: it
  optimises for review convenience at the cost of long-term clarity. Approach
  B deleted a misleading module (`cache.py`) and required updating five files;
  Approach A would have saved those edits but kept an indirection layer alive
  with no purpose other than backwards compatibility for an audience that does
  not exist.
- I would measure more carefully next time: the "before" miss latency (0.567s)
  was captured mid-session with warm pools, while the "after" miss (1.482s)
  was captured cold immediately after restart. I'd add a warm-up request
  before the miss measurement to make the numbers comparable.
- Worth remembering: `SimpleNamespace` from the standard library is a fast,
  zero-import way to create duck-typed fake objects in unit tests. You only
  need to define the attributes the code under test actually accesses — it is
  a cleaner alternative to `MagicMock()` when the object shape is simple and
  static.

## Related

- `docs/tech-debt.md` — TD-020 (Resolved, S7-4), TD-015 (updated with
  before/after measurements).
- `app/core/redis.py` — `create_redis_client` / `get_redis_client` /
  `RedisDep`.
- `app/main.py` — lifespan context manager.
- `tests/conftest.py` — `_make_redis_override`, `async_client`,
  `unauthed_client`.
