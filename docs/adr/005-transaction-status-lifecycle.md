# ADR-005: Transaction Status Lifecycle (PENDING / POSTED / VOIDED)

## Status

Accepted

## Context

An immutable ledger never deletes or updates posted transactions.
However, real-world accounting requires a way to cancel a transaction — for
example, when an invoice is disputed or a payment is reversed.
Without a status field, cancellation would require physical deletion,
which destroys the audit trail.

Additionally, some systems require an approval step before a transaction affects balances
(two-phase commit: create as PENDING, then POST after approval).

## Decision

Add `status ENUM (PENDING, POSTED, VOIDED)` to the `transactions` table.

All transactions are immediately set to `POSTED` on creation.
`VOIDED` is applied via `POST /api/v1/transactions/{id}/void`, which creates
a paired reversal transaction with opposite entry signs.

## State Machine

```
PENDING ──► POSTED ──► VOIDED
                 ▲
          (created here in MVP)
```

| Status | Meaning |
|--------|---------|
| `PENDING` | Created but not yet committed to the ledger. Entries do not affect balances. Reserved for future approval workflows.|
| `POSTED` | Committed to the ledger. Entries affect balances. Amounts and entries are immutable; only a controlled transition to `VOIDED` is permitted. |
| `VOIDED` | Cancelled. A paired reversal transaction with opposite entry signs is created. The original transaction remains intact for audit purposes **and still counts toward balance** — it is the reversal, not exclusion, that nets the effect back to zero. |

## Rationale

- **Immutability**: amounts and entries are never UPDATE-d or DELETE-d;
  `status` is the single controlled mutable field, and its transitions form a state machine
  (`PENDING → POSTED → VOIDED`), not an arbitrary edit
- **Auditability**: VOIDED transactions remain in the ledger with their original entries
- **Extensibility**: PENDING state enables future approval / two-phase-commit workflows
  without schema changes

## Consequences

- **Enforcement layer**: this immutability rule is enforced by the application layer
  (no update/delete endpoints exist for `transactions` or `entries`) and by convention
  documented here — it is **not** additionally backstopped by a database-level
  `REVOKE`/trigger today. See ADR-007's Trade-offs (the balance trigger fires on
  `INSERT` only and does not guard `UPDATE`/`DELETE`) and TD-055 for the tracked gap.
- Balance queries must filter `WHERE status IN ('POSTED', 'VOIDED')`
  (only `PENDING` is excluded) — a void's paired reversal only nets to zero
  because the original stays balance-effective; excluding `VOIDED` entirely would leave
  a `-original` residual instead of `0`
- Voiding a transaction creates a new reversal transaction (opposite entry signs),
  not a DELETE
- `posted_at TIMESTAMPTZ` records the exact moment of the PENDING → POSTED transition
- Within the application's own write path, the `POSTED → VOIDED` transition is
  enforced atomically at the database level via a conditional
  `UPDATE ... WHERE status = 'POSTED'` (compare-and-swap), not by reading
  `status` in application code and writing unconditionally. Two concurrent
  void requests for the same transaction therefore resolve to exactly one
  success and one `409 Conflict`, never two reversals.
- The reversal transaction created on void inherits `original.transaction_date`
  (see `transaction_service.py`), not the void operation's own date. This means
  voiding erases the original transaction's effect from every `as_of` point in
  time, including past ones — the paired reversal always nets to zero at any
  historical balance query, not just from the void date forward. This is a
  deliberate choice favoring pair symmetry and point-in-time consistency over
  the period-closing convention used by systems with a formal close (e.g.,
  SAP-style reversals that post on the *current* period's date, leaving
  closed-period balances untouched). This system has no period-close concept
  today; if one is introduced, voiding a transaction dated in a closed period
  should be revisited — either the reversal should use the void date (or
  current period date) instead, or closed-period balances should be locked
  against further mutation entirely.

## References

- [Double-entry bookkeeping — voiding transactions](https://en.wikipedia.org/wiki/Double-entry_bookkeeping)
- Implementation: `app/models/transaction.py`, `app/services/transaction_service.py`
  - Void endpoint: `app/api/v1/routes/transactions.py` — `POST /transactions/{id}/void`
- Related: ADR-003 (accounting date), ADR-007 (balance trigger enforcement boundary)
