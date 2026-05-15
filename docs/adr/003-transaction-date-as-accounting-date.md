# ADR-003: Keep `transaction_date DATE` as the Accounting Date

## Status

Accepted — implemented in Sprint S2-X-1

## Context

Two separate concepts exist in ledger systems:

1. **Accounting date** (`transaction_date DATE`): the business date the entry
    belongs to — determines which financial period it affects.
2. **System timestamp** (`posted_at TIMESTAMPTZ`): the wall-clock moment the
    record was physically written to the database.

The original design (`ARCHITECTURE.md`) only had `posted_at TIMESTAMPTZ`,
which conflates these two concepts. A transaction entered on May 1st may
legitimately belong to the April period (month-end close scenario).

## Decision

Keep `transaction_date DATE` as the user-supplied accounting date **and**
add `posted_at TIMESTAMPTZ` as the system-generated commit timestamp.
Both fields are stored on every transaction row.

## Rationale

**Month-end close example**: An accountant enters a transaction on May 1st
for an invoice received on April 30th.
The accounting date is April 30 (`transaction_date = 2024-04-30`)
so it falls in April's P&L.
The system records `posted_at = 2024-05-01T09:32:00Z`
as the audit trail timestamp.
Balance queries use `WHERE transaction_date <= '2024-04-30'` to produce
correct April figures.

| Field | Type | Meaning |
|-------|------|---------|
| `transaction_date` | `DATE` | Accounting date — which period this entry belongs to |
| `posted_at` | `TIMESTAMPTZ` | System timestamp — when the record was written |
| `created_at` | `TIMESTAMPTZ` | Row creation timestamp (audit trail) |

## Analogy to Traditional Accounting Systems

SAP uses the same two-field pattern under different names:

| This system | SAP field | SAP name (DE) |
|-------------|-----------|----------------|
| `transaction_date` | `BLDAT` | Belegdatum (document date) |
| `posted_at` | `BUDAT` | Buchungsdatum (posting date) |

## Consequences

- Balance queries use `transaction_date <= as_of` (not `posted_at`) to respect accounting periods
- Backdated entries are possible by design — access control to prevent abuse is deferred (TD-002)
- `posted_at` is set by the service layer at creation time; not user-supplied

## References

- [SAP Document Date vs Posting Date](https://help.sap.com/docs/)
- Implementation: `app/models/transaction.py`
- Related: ADR-005 (transaction status lifecycle)
