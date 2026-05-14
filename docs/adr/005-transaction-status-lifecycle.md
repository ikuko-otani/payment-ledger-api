# ADR-005: Transaction Status Lifecycle (PENDING / POSTED / VOIDED)

## Status

Accepted — implemented in Sprint S2-X-1

## Context

<!-- 🔧 TODO: explain why a status field is needed on an immutable ledger
hint: ADR-004 says transactions are never deleted or updated after POSTED;
      but we need a way to mark a transaction as cancelled without deleting it.
      Also, some systems have a two-phase commit (create PENDING, then POST)
      to support approval workflows.
-->

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

<!-- 🔧 TODO: explain what each state means
hint:
  PENDING  = created but not yet committed to the ledger (future: approval workflows)
  POSTED   = committed; entries affect balances; immutable
  VOIDED   = cancelled; a paired reversal transaction is created (not deleted)
-->

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
