# Fix: Idempotency Key Release on Failure + Commit-Before-Cache-Invalidation (TD-017/018)

**Date**: 2026-06-09
**Branch**: `feature/fix-idempotency-cache-commit-boundary`
**PR**: #41
**Tech debt resolved**: TD-017, TD-018

---

## Background

Two transaction boundary bugs were identified during the pre-S6 design review.
Both are silent in normal operation but cause observable failures under specific
error conditions.

---

## TD-017 — Idempotency Key Leaked on Request Failure

### Problem

`check_idempotency` was a plain `async def` dependency returning `None`.
When the route handler succeeded, everything was fine. But when the handler
raised (e.g., 422 Unprocessable Entity), the Redis key set before the `yield`
was never deleted, permanently blocking retries with the same key for 24 hours.

```
Client sends request A  →  Redis: SET idempotency:<key>  ✅
Handler raises 422      →  Redis key remains ❌
Client retries with same key  →  409 Conflict (incorrect)
```

### Root cause

FastAPI only runs cleanup code after a `yield`-based dependency if the
dependency is a **generator**. A plain `async def` that returns has no
cleanup hook — the framework has nowhere to run "undo" logic on failure.

### Fix

Convert `check_idempotency` to an `AsyncGenerator`:

```python
async def check_idempotency(
    redis: RedisDep,
    idempotency_key: Annotated[uuid.UUID | None, Header()] = None,
) -> AsyncGenerator[None, None]:
    if idempotency_key is None:
        yield
        return

    redis_key = f"{_REDIS_KEY_PREFIX}{idempotency_key}"
    was_set = await redis.set(redis_key, "1", nx=True, ex=_IDEMPOTENCY_TTL_SECONDS)
    if not was_set:
        raise HTTPException(status_code=409, detail="Duplicate request: ...")

    try:
        yield                          # ← route handler runs here
    except Exception:
        await redis.delete(redis_key)  # ← cleanup on any failure
        raise
```

When the route handler raises, FastAPI calls `.athrow(exc)` on the generator,
which lands in the `except` block. This is equivalent to RAII in C++, or PHP's
`try/finally` pattern — the cleanup is guaranteed regardless of how the handler
exits.

### How FastAPI routes generator dependencies

```
Request arrives
    │
    ▼
check_idempotency runs up to yield
    │
    ▼
Route handler executes
    │
    ├─ success → generator.asend(None) → finally runs
    └─ failure → generator.athrow(exc) → except block runs, key deleted
```

---

## TD-018 — Balance Cache Invalidated Before DB Commit

### Problem

In `post_transaction`, the original order was:

```python
transaction = await create_transaction(db, payload, current_user.id)
# (implicit: get_db will commit after the route returns)
for entry in payload.entries:
    keys = await redis.keys(f"balance:{entry.account_id}:*")
    if keys:
        await redis.delete(*keys)   # ← cache cleared here
return transaction
# (get_db commits here — AFTER the handler returned)
```

Between `redis.delete` and `get_db`'s commit, a concurrent `GET /balance`
request could miss the cache and re-query the DB — finding the old balance
(transaction not yet committed) — and write that stale value back into Redis.

```
Thread A: redis.delete ─────────────────────────── get_db commits
Thread B:               GET /balance → cache miss → DB read (stale) → redis.set (stale)
```

### Fix

Add an explicit `await db.commit()` **before** the `redis.delete` loop:

```python
transaction = await create_transaction(db, payload, current_user.id)
await db.commit()                  # ← commit first, close the window
for entry in payload.entries:
    keys = await redis.keys(f"balance:{entry.account_id}:*")
    if keys:
        await redis.delete(*keys)  # ← now safe: DB is consistent
return transaction
```

`get_db`'s own commit (in the `finally` block) becomes a no-op because the
session is already clean after an explicit commit.

### Why the window exists in the first place

FastAPI's `get_db` dependency uses `yield` and commits in the cleanup phase:

```python
async def get_db():
    async with AsyncSession(engine) as session:
        try:
            yield session
            await session.commit()   # ← runs after route handler returns
        except Exception:
            await session.rollback()
            raise
```

This "Open Session in View" pattern means the commit happens at framework
level, not at the business logic level. Explicit `db.commit()` in the route
handler is the correct way to take control of the commit boundary when
subsequent steps (like cache invalidation) must happen in a specific order.

---

## Testing Strategy

### TD-017 test: key released on failure, retry succeeds

```python
async def test_failed_transaction_releases_idempotency_key_for_retry(...):
    key = str(uuid.uuid4())

    # Step 1: unbalanced → 422 (handler raises after key is set)
    r1 = await idempotent_client.post("/api/v1/transactions",
                                      json=bad_payload,
                                      headers={"Idempotency-Key": key})
    assert r1.status_code == 422

    # Step 2: retry with same key and valid payload → 201 (key was released)
    r2 = await idempotent_client.post("/api/v1/transactions",
                                      json=good_payload,
                                      headers={"Idempotency-Key": key})
    assert r2.status_code == 201
```

### TD-018 test: balance endpoint reflects committed transaction

```python
async def test_balance_reflects_new_transaction_after_commit(...):
    r_post = await full_flow_client.post("/api/v1/transactions", json=payload)
    assert r_post.status_code == 201

    r_balance = await full_flow_client.get(f"/api/v1/accounts/{acc_debit.id}/balance", ...)
    assert r_balance.status_code == 200
    assert r_balance.json()["balance"] == 500
```

### The `full_flow_client` fixture

The balance test required overriding **two** Redis dependencies:
- `get_redis` (idempotency.py) — used by `check_idempotency`
- `get_redis_client` (core/cache.py) — used by the balance cache

A separate `full_flow_client` fixture was needed because `idempotent_client`
only overrides `get_redis`. Overriding both ensures the test container Redis
is used end-to-end and the balance cache behaviour is observable in tests.

---

## Key Takeaways

### What did I learn?

- FastAPI `yield`-based dependencies are the correct mechanism for resource
  lifecycle management. The `try/except` around `yield` is the FastAPI
  equivalent of RAII: setup before yield, teardown in the except/finally block.
  A plain `async def` dependency has no cleanup hook at all.
- The OSIV (Open Session in View) pattern that `get_db` implements moves the
  commit to framework level — after the route handler returns. This is
  convenient by default but requires explicit `db.commit()` in the route when
  later steps depend on the DB being consistent (e.g., cache invalidation).
- Testing Redis integration requires overriding every dependency that creates a
  Redis client. In this codebase there were two (`get_redis` and
  `get_redis_client`) that needed separate override paths.

### What would I do differently?

- I would write the cleanup path test (TD-017: retry after failure) at the
  same time as the feature is first implemented — the bug is invisible in
  the happy path and only appears under failure.
- I would document the OSIV commit order assumption in a comment in `get_db`
  so that future route handlers know that explicit `db.commit()` is needed
  when post-commit side effects must run.

### What surprised me?

- That FastAPI silently does nothing when a plain `async def` dependency
  finishes and the route raises. The `yield`-based form is required for any
  resource that needs cleanup on failure — it is not just a style preference.
- That the balance cache stale-read race is completely invisible in tests
  unless both Redis dependencies are overridden to the same test container
  client. With two separate in-memory clients, the test would pass even with
  the bug.

### What is worth remembering for future goals?

- Any dependency that writes a side-effectful resource (Redis key, file lock,
  audit record) before `yield` must wrap the `yield` in `try/except` to
  guarantee cleanup on failure — not just on success.
- When a route needs to trigger side effects (cache invalidation, webhook,
  outbox write) that must see committed data, add `await db.commit()` in
  the route before those side effects. Do not rely on `get_db`'s implicit
  post-return commit.
- When writing tests for cache behaviour, enumerate all Redis dependency
  functions in the app and make sure the fixture overrides every one.
