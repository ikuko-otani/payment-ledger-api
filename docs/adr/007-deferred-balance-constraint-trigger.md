# ADR-007: Deferred Constraint Trigger for Double-Entry Balance Enforcement

## Status

Accepted

## Context

The double-entry invariant (`SUM(debit amounts) = SUM(credit amounts)` per
transaction) is validated in the service layer before persisting. However,
writes that bypass the service layer — direct SQL, migration scripts, admin
tools — could violate the invariant without detection.

A plain `CHECK` constraint cannot enforce this rule because it operates on a
single row and cannot aggregate across multiple `entries` rows belonging to the
same transaction. A regular `AFTER INSERT` trigger would fire after each
individual `INSERT`, when only one side of the double entry exists, and
immediately reject it.

## Decision

Add a PostgreSQL `CONSTRAINT TRIGGER` with `DEFERRABLE INITIALLY DEFERRED` on
the `entries` table. The trigger fires at `COMMIT` time — when all entries for
the transaction are present — and raises `check_violation` (SQLSTATE 23514) if
debits ≠ credits.

```sql
CREATE CONSTRAINT TRIGGER trg_check_entries_balance
AFTER INSERT ON entries
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION check_entries_balance();
```

## Rationale

| Approach | Fires when | Can see all entries | Blocks valid partial inserts |
|----------|-----------|--------------------|-----------------------------|
| `CHECK` constraint | Per row | No | Yes |
| `AFTER INSERT` trigger | Per row | No | Yes |
| `AFTER INSERT ... DEFERRABLE INITIALLY DEFERRED` | At `COMMIT` | Yes | No |

The deferred trigger is the only PostgreSQL mechanism that can aggregate across
rows *and* wait until all rows are present before validating.

This creates a defense-in-depth model:

1. **Service layer** (primary) — validates before persisting, returns a clear
   `422` error with debit/credit sums in the message.
2. **Database trigger** (safety net) — catches any write that bypasses the
   service layer, raising a database-level exception at commit.

## Trade-offs

- The trigger fires once **per inserted row** at commit time, not once per
  transaction. For a transaction with N entries, the balance check query runs
  N times. At typical entry counts (2–6 per transaction) this is negligible;
  a `STATEMENT`-level trigger would be more efficient but cannot access `NEW`.
- The trigger only covers `INSERT`. Direct `UPDATE` or `DELETE` on `entries`
  would bypass it — but the ledger's immutability rule (ADR-005) prohibits
  updates and deletes on posted entries, so this is acceptable.

## Consequences

- Any write path — application, migration, `psql` — is protected against
  unbalanced entries.
- The service-layer validation is not redundant: it provides user-friendly
  error messages before the transaction reaches the database, avoiding a
  commit-time exception that would be harder for clients to interpret.
- Migration: `alembic/versions/20260623_1400_dba49c02eafb_add_balance_check_constraint_trigger.py`

## References

- [PostgreSQL: CREATE TRIGGER — constraint triggers](https://www.postgresql.org/docs/16/sql-createtrigger.html)
- `ARCHITECTURE.md` §3 — Double-entry balance enforced at two layers
- `app/services/transaction_service.py` — service-layer validation
- `ADR-005` — immutable ledger (no UPDATE/DELETE on posted entries)
