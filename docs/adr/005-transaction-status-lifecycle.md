# ADR-005: Transaction Status Lifecycle (PENDING / POSTED / VOIDED)

## Status

Accepted — implemented in Sprint S2-X-1

## Context

An immutable ledger never deletes or updates posted transactions (ADR-004).
However, real-world accounting requires a way to cancel a transaction — for
example, when an invoice is disputed or a payment is reversed.
Without astatus field, cancellation would require physical deletion,
which destroys the audit trail.

Additionally, some systems require an approval step
before a transaction affects balances
(two-phase commit: create as PENDING, then POST after approval).
A status field enables this workflow without schema changes.

## Decision

Add `status ENUM (PENDING, POSTED, VOIDED)` to the `transactions` table.

For MVP, all transactions are immediately set to `POSTED` on creation.
`VOIDED` is reserved for future reversal support.

## State Machine

```
PENDING ──► POSTED ──► VOIDED
                 ▲
          (created here in MVP)
```

| Status | Meaning |
|--------|---------|
| `PENDING` | Created but not yet committed to the ledger. Entries do not affect balances. Reserved for future approval workflows.|
| `POSTED` | Committed to the ledger. Entries affect balances. Immutable — never updated or deleted. |
| `VOIDED` | Cancelled. A paired reversal transaction with opposite entry signs is created. The original transaction remains intact for audit purposes. |

## Rationale

- **Immutability**: once POSTED, a transaction row is never UPDATE-d or DELETE-d
- **Auditability**: VOIDED transactions remain in the ledger with their original entries
- **Extensibility**: PENDING state enables future approval / two-phase-commit workflows without schema changes

## Consequences

- Balance queries must filter `WHERE status = 'POSTED'` to exclude voided entries
- Voiding a transaction creates a new reversal transaction (opposite entry signs), not a DELETE
- `posted_at TIMESTAMPTZ` records the exact moment of the PENDING → POSTED transition

## References

- [Double-entry bookkeeping — voiding transactions](https://en.wikipedia.org/wiki/Double-entry_bookkeeping)
- Implementation: `app/models/transaction.py`, `app/services/transaction_service.py`
- Related: ADR-003 (accounting date), ADR-004 (immutable log)
