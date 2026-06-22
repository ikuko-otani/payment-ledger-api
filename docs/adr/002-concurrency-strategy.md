# ADR-002: Concurrency Strategy — No Stored Balance, No Row-Level Locks

## Status

Accepted

## Context

A double-entry ledger must remain consistent under concurrent writes.
Two clients may simultaneously post transactions that affect the same account,
raising the question: how do we prevent race conditions on account balances?

Three approaches were considered:

1. **Stored balance with pessimistic locking** — maintain a `balance` column on
   `accounts` and acquire `SELECT ... FOR UPDATE` before every write. Each
   transaction updates the stored balance atomically.
2. **Stored balance with optimistic locking** — add a `version` column;
   read-then-CAS with a retry loop on conflict.
3. **Computed balance (no stored balance)** — balance is always derived at read
   time via `SUM(CASE debit/credit)` over the `entries` table. No mutable
   balance column exists; no row-level lock is needed for writes.

## Decision

Use **computed balance** (option 3).

Balance is calculated on demand by aggregating all `POSTED` entries for a given
account (`AccountRepository.calculate_balance`). The `accounts` table has no
`balance` column.

Transaction writes (`POST /transactions`) do not lock any account rows. Each
write inserts a new `Transaction` + `Entry` set within a single PostgreSQL
transaction at the default `READ COMMITTED` isolation level.

## Rationale

| Factor | Stored + pessimistic | Stored + optimistic | Computed (chosen) |
|--------|---------------------|--------------------|--------------------|
| Write contention | High — hot accounts serialize | Medium — retries under contention | **None** — inserts never conflict |
| Consistency guarantee | Strong (lock-based) | Strong (CAS-based) | Strong (derived from immutable entries) |
| Read cost | O(1) — read column | O(1) — read column | O(N) — aggregate query |
| Implementation complexity | Medium (lock ordering, deadlocks) | Medium (retry logic, version checks) | **Low** — no locks, no retries |
| Scaling pattern | Lock contention grows with TPS | Retry storms under high contention | Scales linearly with workers |

Key arguments for computed balance in this system:

- **Entries are append-only.** Transactions are never updated or deleted
  (see [ADR-005](005-transaction-status-lifecycle.md)). This means the
  aggregate query over entries is deterministic — it reads immutable data.
- **No write-write conflict.** Two concurrent `POST /transactions` each
  `INSERT` their own rows. PostgreSQL handles row-level insert concurrency
  natively; no explicit locking is needed.
- **Read cost is mitigated by caching.** `GET /accounts/{id}/balance` uses
  a Redis Cache-Aside layer (see [ARCHITECTURE.md §8.3](../ARCHITECTURE.md)).
  Cache invalidation happens after each transaction commit via `SCAN`-based
  key deletion.
- **No deadlock risk.** Pessimistic locking on multiple accounts within a
  single multi-entry transaction requires careful lock ordering to avoid
  deadlocks. The computed approach sidesteps this entirely.

### Where row-level protection IS used

- **Idempotency keys**: `SET NX` in Redis provides atomic mutual exclusion
  for duplicate detection (see [ADR-001](001-redis-for-idempotency-key.md)).
- **Unique constraints**: `users.email` and `currencies.code` uniqueness is
  enforced by PostgreSQL `UNIQUE` indexes. Concurrent duplicates are caught
  via `try/except IntegrityError` (optimistic, DB-enforced).

## Consequences

- Balance reads require an aggregate query over the entries table. For accounts
  with a very large number of entries (millions), query time will grow. In a
  production system, this would be addressed with a materialized balance
  snapshot (periodic aggregation) or partitioning — neither is needed at the
  current scale.
- The system does not enforce a minimum balance or overdraft limit at the
  database level. If such a constraint were added, the computed approach would
  need revisiting — either switching to a stored balance with locking, or
  adding a `SERIALIZABLE` isolation level for the check-then-write path.
- No explicit `SELECT ... FOR UPDATE` means the system relies on PostgreSQL's
  `READ COMMITTED` isolation and the append-only invariant for correctness.
  Introducing mutable entries (e.g., amount edits) would break this assumption.

## References

- Balance calculation: `app/repositories/account_repository.py` — `calculate_balance`
- Cache-Aside layer: `app/api/v1/routes/accounts.py` — `get_account_balance`
- Idempotency (Redis SET NX): `app/dependencies/idempotency.py`
- Immutable transactions: [ADR-005](005-transaction-status-lifecycle.md)
