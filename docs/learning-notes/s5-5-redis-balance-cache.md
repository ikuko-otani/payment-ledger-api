# S5-5: Redis Balance Cache — Learning Notes

**Goal**: Add Cache-Aside caching to `GET /accounts/{id}/balance` using Redis.
**Branch**: `feature/s5-5-redis-balance-cache`
**Date**: 2026-06-05

---

## Step C Walkthrough

See scaffold and implementation in:
- `app/core/cache.py` — `get_redis_client()` dependency
- `app/api/v1/routes/accounts.py` — Cache-Aside logic
- `app/api/v1/routes/transactions.py` — cache invalidation on POST
- `tests/test_balance_cache.py` — hit / miss / invalidation tests

---

## Q: Why store balance in Redis cache rather than a DB table?

Redis cache is used for **read speed**, not as a source of truth.

| Approach | Description |
|---|---|
| Redis cache (this project) | Temporary copy of a computed value. Deleted on write, rebuilt on next read. DB remains the source of truth. |
| DB balance snapshot table | Precomputed balance stored in a separate DB table alongside journal entries. Requires schema changes and write-path consistency guarantees. |

Redis avoids schema changes and keeps consistency simple: when a transaction is posted, the cache key is deleted. The next GET recomputes from DB and repopulates the cache.

---

## Q: Is the "nightly batch to update balance tables" pattern in core banking systems outdated?

Not obsolete — but the reason for using it has shifted.

### Why it persists in traditional banking

- **Regulatory requirements**: Basel III and similar regulations mandate end-of-day (EOD) balance reporting. A nightly batch produces the authoritative daily snapshot used for audit and compliance.
- **Historical constraints**: Mainframe + COBOL systems couldn't aggregate in real time. Nightly batch was the practical solution.
- **Audit trail**: A committed EOD balance row is easier to certify than a dynamically computed value.

### What modern fintech does instead (CQRS + event-driven)

Fintechs like Mollie, Revolut, and Stripe use **CQRS (Command Query Responsibility Segregation)**:

```
Write model  →  journal entry INSERT  →  event published
                                               ↓
Read model   ←  balance view updated  ←  event consumed (real-time)
```

The read model (balance) is updated the moment a transaction is confirmed — no overnight wait. This also maps naturally to event sourcing, where every transaction is an immutable event and the balance is always derivable from the event log.

### Relationship to this project

This project's design (compute balance from journal entries on demand, cache the result) is conceptually aligned with the CQRS starting point: the write model (entries table) is the source of truth, and the Redis cache is the read optimization layer.

**For EU fintech roles (Mollie, Revolut, etc.)**: being able to explain both the legacy batch approach and the modern event-driven alternative — and articulate *why* each exists — is a strong signal in system design interviews.

---

## Related

- ADR: `docs/adr/001-redis-for-idempotency-key.md`
- Cache invalidation implementation: `app/api/v1/routes/transactions.py`
- Cache-Aside pattern: `app/api/v1/routes/accounts.py`

---

## Key Takeaways

### What did I learn?

- I learned how to implement the **Cache-Aside (Lazy Loading) pattern** end-to-end: cache key design with `as_of_date`, TTL via environment variable, `str`/`int` round-trip serialization, and cache invalidation on write.
- I learned that **FastAPI `dependency_overrides` completely bypasses the original function** — the overridden function is never called. This means a bug inside a dependency function (like the `decode_response` typo) is invisible to tests that override that dependency.
- I learned the difference between **Docker service names** (only resolvable inside the Docker network) and **`localhost` with port mapping** (accessible from the host), and why `uv run pytest` on the host cannot reach `redis://redis:6379`.
- I learned how to **refactor shared test fixtures** using a helper function (`_make_redis_override`) modelled after the existing `_make_db_override` pattern, and why `session`-scoped container fixtures belong in `conftest.py` rather than individual test files.
- I learned the distinction between the legacy **nightly batch** balance update pattern (driven by regulatory/mainframe constraints) and the modern **CQRS + event-driven** approach used by fintechs like Mollie and Revolut.

### What would I do differently?

- I would extract `_make_redis_override` from the start, rather than adding it as a refactor after the initial implementation caused test failures across existing tests. Planning which fixtures need a new dependency before writing any code would have saved a round of debugging.
- I would run a quick smoke test (`curl` or a direct Python call) on the dependency function itself early, rather than waiting until the full manual verification step. The `decode_response` typo would have been caught much sooner.

### What surprised me?

- It surprised me that **all cache tests passed even though `get_redis_client()` had a typo** that would crash at runtime. The dependency override pattern is powerful, but it means the production code path for the dependency itself is untested unless you call the function directly.
- The structural issue in `authenticated_client` — where `_redis` was created inside `_factory` and therefore could never be closed — was a subtle lifecycle bug that only became visible when I thought carefully about the fixture's teardown flow.

### What is worth remembering for future goals?

- **`if cached is not None:` not `if cached:`** — a cached value of `"0"` is falsy in Python, so the shorter form silently skips the cache hit for zero balances.
- **Cache key must include all query parameters** — `balance:{account_id}` alone is wrong; `balance:{account_id}:{as_of_date}` is correct. Missing a parameter means different queries share the same key and return stale results.
- **Invalidate both debit and credit accounts** — a transaction touches two accounts. Only invalidating one leaves the other with a stale balance.
- **`session`-scoped container fixtures belong in `conftest.py`** — if two test files both define a `session`-scoped `redis_container`, pytest starts two containers. One shared fixture in `conftest.py` is the correct design.
- **`decode_responses=True` (plural)** — the `redis.asyncio` parameter is `decode_responses`, not `decode_response`. This typo produces a `TypeError` at runtime but is invisible in tests that use dependency overrides.
