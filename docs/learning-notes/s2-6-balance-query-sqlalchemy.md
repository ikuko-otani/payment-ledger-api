# S2-6: Balance Calculation Query (SQLAlchemy)

**Date**: 2026-05-17
**Goal**: Implement `calculate_balance` service using SQLAlchemy aggregate query; wire into `GET /accounts/{id}/balance`
**Branch**: `feature/s2-6-balance-query-sqlalchemy`
**Support level**: balanced

---

## Step C Walkthrough

### C-1. Implement `calculate_balance` (`app/services/balance.py`)

Created a new service function that computes the balance for a given account up to
`as_of` (inclusive) using a single SQL aggregate query.

```python
async def calculate_balance(
    db: AsyncSession,
    account_id: uuid.UUID,
    as_of: datetime,
) -> int:
    result = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    case((Entry.direction == Direction.DEBIT, Entry.amount), else_=0)
                ),
                0,
            )
            - func.coalesce(
                func.sum(
                    case((Entry.direction == Direction.CREDIT, Entry.amount), else_=0)
                ),
                0,
            )
        )
        .join(Transaction, Entry.transaction_id == Transaction.id)
        .where(
            Entry.account_id == account_id,
            Transaction.transaction_date <= as_of.date(),
            Transaction.status == TransactionStatus.POSTED,
        )
    )
    return result.scalar_one()
```

Key design decisions:

- **Single query with conditional `SUM`** — `SUM(CASE WHEN direction='debit' THEN amount ELSE 0 END)`
  computes both sides in one DB round-trip. Splitting into two queries risks a read skew
  if another transaction commits between them.
- **`func.coalesce(..., 0)`** — `SUM()` returns `NULL` when no rows match the filter.
  Wrapping in `COALESCE` at the DB layer avoids a `None` check in Python.
- **`as_of.date()`** — `transaction_date` is stored as `date`; `as_of` is a `datetime`.
  The `.date()` conversion aligns types before comparison.
- **`status == POSTED` filter** — VOIDED transactions are not physically deleted
  (per ADR-005). Explicit status filtering prevents VOIDED entries from affecting
  the balance.

### C-2. Wire service into route (`app/api/v1/routes/accounts.py`)

Added `db: DbDep` parameter and replaced the stub return with a service call.

```python
@router.get("/{id}/balance", response_model=BalanceResponse)
async def get_account_balance(
    id: uuid.UUID,
    as_of: datetime,
    db: DbDep,
) -> BalanceResponse:
    balance = await calculate_balance(db, id, as_of)
    return BalanceResponse(balance=balance, as_of=as_of)
```

### C-3. Tests (`tests/test_balance.py`)

Added five integration tests:

| Test | What it verifies |
|------|-----------------|
| `test_balance_single_debit_equals_amount` | POSTED debit entry is reflected in balance |
| `test_balance_excludes_transaction_after_as_of` | Transactions after `as_of` are excluded |
| `test_balance_excludes_voided_transaction` | VOIDED transactions do not affect balance |
| `test_balance_no_transactions_returns_zero` | Account with no transactions returns 0 |
| `test_get_balance_endpoint_returns_correct_value` | HTTP end-to-end check via `AsyncClient` |

Common mistakes encountered during test authoring:

- **`(2026, 1, 10)` instead of `date(2026, 1, 10)`** — Python treats bare parenthesised
  values as a tuple. asyncpg raised a `DataError` with `'tuple' object has no attribute
  'toordinal'`, which is the datetime library's way of saying it received the wrong type.
- **`json={ {dict1}, {dict2} }` instead of a proper dict** — Python interprets this as a
  set literal. Because dicts are unhashable, it raises `TypeError: unhashable type: 'dict'`
  at runtime.
- **Missing `/api/v1` prefix** — The router is mounted at `/api/v1`; HTTP tests must use
  the full path (e.g., `/api/v1/accounts`), not the bare resource path.

---

## Key Takeaways

**What did I learn?**

I learned how to use SQLAlchemy's `func.sum()` combined with `case()` to perform
conditional aggregation in a single query. The pattern — one `SELECT` that computes
debit and credit totals simultaneously — is the ORM equivalent of a SQL `SUM(CASE WHEN
...)` expression. I also learned that `func.coalesce()` must be applied around each
`func.sum()` individually: if no rows match, `SUM` returns `NULL`, and subtracting
`NULL` from anything propagates `NULL` rather than returning zero.

The type mismatch between `datetime` (the `as_of` API parameter) and `date` (the
`transaction_date` column) was a concrete reminder that SQLAlchemy does not auto-coerce
Python types — the comparison must use `as_of.date()`.

**What would I do differently?**

I would mentally check the URL prefix before writing any `async_client` calls. The
`/api/v1` prefix is defined in `app/api/v1/router.py` and is easy to overlook when
copying patterns from endpoint-level code. Checking the router file first would save a
debugging round.

I would also slow down when typing `date(YYYY, M, D)` — the tuple typo `(YYYY, M, D)`
is visually similar and produces a non-obvious asyncpg error (`toordinal`) rather than a
clear `TypeError`.

**What surprised me?**

I was surprised that `SUM()` returns `NULL` rather than `0` for an empty result set.
In most imperative loops, summing an empty sequence yields 0 naturally. SQL's behaviour
is different, and forgetting `COALESCE` would cause the service to return `None` instead
of `0` for accounts with no transactions — a silent bug that would only surface at
runtime.

**What is worth remembering for future goals?**

- HTTP integration tests require the full `/api/v1/...` path — check `router.py` before
  writing the first `async_client` call.
- `func.coalesce(func.sum(...), 0)` is the standard pattern for safe conditional
  aggregation in SQLAlchemy; apply it to each conditional sum individually.
- `date()` constructor vs tuple literal: `date(2026, 1, 10)` and `(2026, 1, 10)` look
  similar but produce completely different Python objects. asyncpg's `toordinal` error is
  the signal that a tuple was passed where a `date` was expected.
- POST request bodies in `httpx` must be a properly structured dict under `json=`; a set
  literal compiles silently but fails at the first hashability check.
