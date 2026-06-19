# S8-2: Idempotency Response Replay (Stripe-style)

**Date**: 2026-06-19
**Branch**: feature/s8-2-idempotency-response-replay
**Goal**: Replace 409 Conflict on duplicate Idempotency-Key with 200 + cached response body (TD-004/005).

---

## Step C Walkthrough

### Overview: Two-phase Redis state machine

Before S8-2, the Redis key held the string `"1"` as a marker ("key used").
After S8-2, the key moves through two states:

```
[key absent]
     │  SET NX key "__pending__"  (atomic, new request wins)
     ▼
[key = "__pending__"]
     │  route handler succeeds → SET key <JSON>
     ▼
[key = <JSON response body>]
     │  TTL 24h elapses
     ▼
[key absent]
```

A duplicate request arriving in any state is handled as follows:

| Redis state at arrival | Action |
|------------------------|--------|
| Absent                 | SET NX → new request |
| `"__pending__"`        | 409 (in-flight duplicate) |
| Valid JSON             | 200 + replay cached body |

---

### Step 1 — `IdempotencyContext` class (`app/dependencies/idempotency.py`)

```python
class IdempotencyContext:
    def __init__(
        self,
        replay: dict | None = None,
        redis: aioredis.Redis | None = None,
        redis_key: str = "",
    ) -> None:
        self.replay = replay
        self._redis = redis
        self._redis_key = redis_key

    async def cache(self, response_body: dict) -> None:
        if self._redis is not None and self._redis_key:
            await self._redis.set(
                self._redis_key,
                json.dumps(response_body),
                ex=_IDEMPOTENCY_TTL_SECONDS,
            )
```

**Why a class instead of `yield None`?**

The generator dependency needs to communicate two things to the route handler:
1. `replay` — the cached response body (if any); the route handler checks this to short-circuit.
2. `cache()` — a method the route handler calls after success to persist the response.

Neither is possible with `yield None`. A mutable object passed through `yield` solves both.

**PHP/PDO analogy**: This is similar to passing a `PDOStatement` into a function.
The caller doesn't construct it — the dependency (DI container) creates it and injects it ready to use.

**Why `_redis` and `_redis_key` are prefixed with `_`**:
They are implementation details of `cache()`. The route handler only needs `replay` and `cache()`.
The underscore signals "don't touch directly".

**Interview point**: The `IdempotencyContext` is a value object that acts as a channel between the
dependency and the route handler. This is the standard pattern when a FastAPI generator dependency
needs bidirectional communication with the handler it wraps.

---

### Step 2 — `check_idempotency` generator (`app/dependencies/idempotency.py`)

```python
async def check_idempotency(
    redis: RedisDep,
    idempotency_key: Annotated[uuid.UUID | None, Header()] = None,
) -> AsyncGenerator[IdempotencyContext, None]:
```

**The generator dependency "sandwich" pattern**:

```
[before yield]  ← setup: check Redis, decide state
      yield ctx  ← FastAPI calls the route handler with ctx
[after yield]   ← teardown: only the except branch runs here
```

The route handler runs in between — exactly like a `try/finally` block that wraps
the route body.

**The three yield paths**:

```python
# Path 1: no header → yield empty context, skip all checks
if idempotency_key is None:
    yield IdempotencyContext()
    return

# Path 2: new request → SET NX, wire up cache()
was_set = await redis.set(redis_key, _PENDING_MARKER, nx=True, ex=86400)
# ...
ctx = IdempotencyContext(redis=redis, redis_key=redis_key)
try:
    yield ctx               # route handler runs here
except Exception:
    await redis.delete(redis_key)   # ← only on failure
    raise

# Path 3: cached hit → populate replay, yield, return (no try/except needed)
yield IdempotencyContext(replay=cached)
return
```

**Why `json.loads()` + `except json.JSONDecodeError` instead of `raw == "__pending__"`?**

`"__pending__"` is not valid JSON (`json.loads("__pending__")` raises `JSONDecodeError`).
Valid JSON from our `cache()` method always starts with `{` (a dict).
Using `try/except json.JSONDecodeError` handles both cases — including any future corruption —
without a fragile string equality check.

**Why `SET NX` is atomic**:
`SET NX` (set-if-not-exists) is a single Redis command. Even if two requests arrive at the
exact same millisecond, Redis serialises them: exactly one gets `True`, the other gets `None`.
This is the same guarantee as `INSERT ... ON CONFLICT DO NOTHING` in PostgreSQL.

---

### Step 3 — `post_transaction` route (`app/api/v1/routes/transactions.py`)

```python
async def post_transaction(
    ...
    idempotency: IdempotencyDep,   # was: _: IdempotencyDep
    ...
) -> Transaction | JSONResponse:

    # ① Early return for cached response
    if idempotency.replay is not None:
        return JSONResponse(content=idempotency.replay, status_code=200)

    # ② Normal processing (unchanged)
    transaction = await create_transaction(...)
    await db.commit()
    for entry in payload.entries:
        ...

    # ③ Cache the response for future replays
    response_data = TransactionRead.model_validate(transaction).model_dump(mode="json")
    await idempotency.cache(response_data)

    return transaction
```

**① Why `return JSONResponse(...)` works even though `response_model=TransactionRead` is set**:

FastAPI only applies `response_model` serialization when the route handler returns a
non-`Response` object. `JSONResponse` inherits from `Response`, so FastAPI passes it
through unchanged — including the `status_code=200` override.

This is the official FastAPI pattern for returning a pre-built response from a route.

**③ Why `model_dump(mode="json")` before `json.dumps()`**:

`transaction` is a SQLAlchemy ORM object. Its fields include:
- `id` → `uuid.UUID` (not JSON-serializable)
- `transaction_date` → `datetime.date` (not JSON-serializable)
- `created_at` → `datetime.datetime` (not JSON-serializable)

`TransactionRead.model_validate(transaction)` converts the ORM object to a Pydantic model.
`model_dump(mode="json")` converts every field to a JSON-safe Python primitive
(`UUID` → `str`, `date` → ISO string, etc.).

After this, `json.dumps(response_data)` works without a custom encoder.

**Why `model_validate` instead of `TransactionRead.from_orm`?**:
`from_orm` is the Pydantic v1 API. Pydantic v2 (used in this project) uses `model_validate`.
They do the same thing — `model_validate` is just the new name.

---

### Step 4 — Test changes (`tests/test_idempotency.py`)

The existing test `test_same_idempotency_key_returns_409_on_second_request` was renamed and
updated to assert the new Stripe-style behaviour:

```python
# Before (S8-1 behaviour):
assert r2.status_code == 409
assert "Idempotency-Key" in r2.json()["detail"]

# After (S8-2 behaviour):
assert r2.status_code == 200
assert r2.json() == r1.json()
```

`r2.json() == r1.json()` verifies that the replayed response body is byte-for-byte identical
to the original — including the transaction ID, created_at timestamp, and all entries.

All other tests are unchanged:
- `test_different_idempotency_keys_both_succeed` — two distinct keys each return 201 ✅
- `test_failed_transaction_releases_idempotency_key_for_retry` — key deleted on failure ✅
- `test_no_idempotency_key_header_succeeds` — no header → no check → 201 ✅

---

### Step 5 — pre-pytest checklist

```bash
uv run ruff format .
uv run ruff check .
uv run mypy --strict app/
```

---

### Step 6 — Run tests

```bash
uv run pytest tests/test_idempotency.py -v
```

Expected: all 7 tests pass.

Full suite:

```bash
uv run pytest --cov=app --cov-report=term-missing -q
```

---

### Step 7 — Close TD-004 and TD-005 in tech-debt.md

Move TD-004 and TD-005 rows from Open to Resolved.

```bash
git add docs/tech-debt.md
git commit -m "docs(s8-2): close TD-004 and TD-005"
```

---

### Step 8 — DONE condition check + PR

DONE conditions:
- [x] Redis に元レスポンス JSON をキャッシュする実装
- [x] 重複キーで 200 + キャッシュ済みレスポンスを返す Depends 更新
- [x] TTL 管理（現在の 24h TTL と整合）
- [x] テスト追加（409 → 200 + ボディ一致）
- [x] TD-004/005 を Resolved に移動

```bash
git push origin feature/s8-2-idempotency-response-replay
gh pr create \
  --title "feat(s8-2): Stripe-style idempotency response replay (TD-004/005)" \
  --body "..."
```

---

## Key Takeaways

### What did I learn?

I learned the FastAPI generator dependency "sandwich" pattern in depth. A `yield`-based `Depends`
splits into three phases: setup (before yield), the route body (during yield), and teardown
(after yield). By yielding a mutable `IdempotencyContext` object instead of `None`, the
dependency can communicate bidirectionally with the route handler — the handler reads
`ctx.replay` to detect a cached hit, and calls `await ctx.cache(...)` to persist the response
after success.

I also learned that `model_dump(mode="json")` is required before `json.dumps()` when serialising
a Pydantic model that contains non-JSON-serialisable types (UUID, datetime, date). The `mode="json"`
flag coerces every field to a JSON-safe Python primitive, so `json.dumps()` needs no custom encoder.

### What would I do differently?

I would add `dict[str, Any]` type annotations from the start instead of writing bare `dict`.
With `mypy --strict`, generic types always need type arguments, and it is faster to get this right
in the first draft than to fix it after the lint step.

### What surprised me?

The `raise ... from None` requirement (ruff B904) surprised me. Even when the new exception
(`HTTPException`) is completely unrelated to the caught one (`JSONDecodeError`), ruff requires
an explicit `from` clause to make the intent clear. `from None` says "I am intentionally
suppressing the original exception" — without it, the full `JSONDecodeError` traceback would be
attached to the `HTTPException`, which leaks internal implementation details.

### What is worth remembering for future goals?

1. **`raise NewException(...) from None`** — use whenever raising a domain/HTTP exception
   inside an `except` block where the original exception is an implementation detail.

2. **`model_dump(mode="json")`** — always required before `json.dumps()` on a Pydantic model.
   `model_dump()` alone returns Python objects (UUID, datetime); `mode="json"` converts them
   to JSON-safe primitives.

3. **`JSONResponse` bypasses `response_model`** — returning a `Response` subclass from a
   FastAPI route skips serialisation and validation entirely. This is the correct pattern for
   replaying a pre-serialised response, but it means the response is not validated against the
   schema at runtime.

4. **`SET NX` as an atomic gate** — a single `SET NX` Redis command is the correct primitive
   for "exactly one winner" concurrency control. The same pattern applies to any resource
   reservation problem (distributed locks, job claiming, etc.).
