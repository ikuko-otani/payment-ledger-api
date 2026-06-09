# Pre-S6 Cleanup — Group A: BigInteger, is_active, pagination (TD-016/011/003/009)

**Date**: 2026-06-09
**Branch**: `feature/pre-s6-cleanup-td016-011-003-009`
**PRs**: #41 (TD-017/018 — idempotency key release + commit-before-cache), #42 (TD-016/011/003/009)
**Goal**: Resolve six open tech-debt items before entering S6 CI expansion,
ensuring the ledger is production-safe with respect to integer overflow,
business rule enforcement, and API contract consistency.

---

## Context

This was not a sprint goal with a Notion task number, but an inter-sprint
cleanup block before S6. The items were grouped from a full codebase design
review that produced TD-016 through TD-022. Group A targeted the four items
with the highest correctness risk.

---

## What Was Done

### TD-017 + TD-018 (PR #41) — Transaction boundary fixes

**TD-017**: `check_idempotency` was a regular `async def` dependency. When the
route handler raised an exception after the idempotency key was written to
Redis, the key was never deleted, blocking all retries for 24 hours.

Fix: converted to an `AsyncGenerator` dependency with a `try/except` block.
FastAPI calls `.athrow()` on generator dependencies when the route raises,
which lands in the `except` arm and triggers `redis.delete`.

```python
async def check_idempotency(...) -> AsyncGenerator[None, None]:
    ...
    try:
        yield
    except Exception:
        await redis.delete(redis_key)
        raise
```

**TD-018**: `redis.delete` (balance cache invalidation) ran before `get_db`'s
auto-commit. A concurrent request could re-populate the cache with the stale
pre-transaction balance during that window.

Fix: explicit `await db.commit()` in the route handler before the
`redis.delete` loop. The second commit inside `get_db`'s `finally` block
becomes a no-op on an already-committed session.

---

### TD-016 (PR #42) — Entry.amount Integer → BigInteger

`Integer` in SQLAlchemy maps to PostgreSQL `INTEGER` (32-bit signed, max
~2.1 billion). For a ledger storing minor currency units (cents), this
overflows at $21.4M USD — a realistic transaction amount.

Fix: changed `mapped_column(Integer, ...)` to `mapped_column(BigInteger, ...)`.
PostgreSQL allows a lossless `ALTER COLUMN ... TYPE BIGINT` with no data
migration needed for existing rows.

Also added `compare_type=True` to `alembic/env.py`'s `context.configure()`.
Without it, Alembic autogenerate ignores column type changes and would silently
skip the migration in future type audits.

---

### TD-011 (PR #42) — is_active filter in create_transaction

The account existence check in `create_transaction` queried by ID only,
accepting inactive accounts. This allowed posting journal entries to
closed/suspended accounts.

Fix: added `.is_(True)` filter to the WHERE clause.

```python
select(Account).where(
    Account.id.in_(account_ids),
    Account.is_active.is_(True),
)
```

`.is_(True)` (SQLAlchemy idiom) was chosen over `== True` because ruff rule
E712 flags equality comparisons to boolean literals as a potential bug pattern.
The two are semantically equivalent in this context (`WHERE is_active IS TRUE`
vs `WHERE is_active = TRUE`), but `.is_(True)` avoids lint noise.

---

### TD-003 (PR #42) — Pagination for GET /transactions

`GET /transactions` had no `limit`/`offset` parameters, returning all rows.
`GET /ledger` and `GET /audit-logs` already had pagination — this was an
inconsistency in the public API contract.

Fix: added `limit: int = Query(default=20, ge=1, le=100)` and
`offset: int = Query(default=0, ge=0)` to `list_transactions`, consistent
with the existing endpoints.

---

### TD-009 (PR #42) — Root /main.py deletion

On inspection, the file was never committed to the repository (`git ls-files`
returned empty). No action required; marked as resolved.

---

## CI Incident: ruff E712

After PR #42 was submitted, CI lint failed with:

```
E712 Avoid equality comparisons to `True`; use `Account.is_active:` for truth checks
```

`ruff check . --fix` did not auto-fix it because ruff classifies the E712 fix
as **unsafe**: replacing `== True` with bare `Account.is_active` could change
semantics in SQLAlchemy expressions (a Column object is always truthy in Python;
only the comparison expression produces the desired SQL `WHERE` clause). Ruff
cannot inspect the ORM context, so it refuses the auto-fix.

Resolution: manual change to `.is_(True)`. The `--unsafe-fixes` flag would
have applied the bare-attribute version, which would be incorrect here.

---

## Key Takeaways

### What did I learn?

- FastAPI generator dependencies (`yield`-based) are the right place for
  resource cleanup on failure. When a route handler raises, FastAPI calls
  `.athrow()` on the generator, landing in the `except` block — equivalent to
  RAII in C++ or `try/finally` in PHP.
- Alembic autogenerate silently skips column type changes unless
  `compare_type=True` is set in `env.py`. This is not the default and is easy
  to overlook for years.
- `INTEGER` overflow in a fintech ledger is a correctness bug, not a
  performance issue. The threshold ($21.4M in cents) is reachable in
  production. BigInteger migration is cheap (lossless in PostgreSQL) and should
  be done early.

### What would I do differently?

- I would add `compare_type=True` from the very first Alembic setup. The
  default that omits type-change detection is a footgun for any project that
  evolves its schema.
- I would run `ruff check .` locally before pushing — the E712 failure was
  caught by CI rather than locally, which added one round-trip.

### What surprised me?

- `ruff check . --fix` reported "1 hidden fix can be enabled with
  `--unsafe-fixes`" for E712. I expected auto-fix to either work or not; the
  concept of a fix being syntactically valid but semantically unsafe in certain
  ORM contexts was new to me.
- TD-009 (root `/main.py`) had never been committed. The file that prompted
  the debt entry may have existed only in the working tree and was removed
  before the initial commit.

### What is worth remembering for future goals?

- For any `yield` dependency that writes a side-effectful resource (Redis key,
  file lock, outbox record), wrap the `yield` in `try/except` to guarantee
  cleanup on failure — not just on success.
- When Alembic autogenerate produces an empty migration for a change you know
  you made, check `compare_type` and `compare_server_default` in `env.py`
  before investigating elsewhere.
- SQLAlchemy boolean column filters: prefer `.is_(True)` / `.is_(False)` over
  `== True` / `== False` to avoid ruff E712 and to produce `IS TRUE` SQL which
  handles NULL correctly.
