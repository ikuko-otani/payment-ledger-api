# ADR-003: Keep `transaction_date DATE` as the Accounting Date

## Status

Accepted — implemented in Sprint S2-X-1

## Context

<!-- 🔧 TODO: explain the problem this decision addresses
hint: two separate concepts exist in ledger systems —
  (1) the business/accounting date (which period the entry belongs to)
  (2) the system timestamp (when the record was physically created)
ARCHITECTURE.md's original design only had posted_at TIMESTAMPTZ, missing (1).
-->

## Decision

<!-- 🔧 TODO: state the decision clearly
hint: keep transaction_date DATE (accounting date) AND add posted_at TIMESTAMPTZ (system timestamp)
-->

## Rationale

<!-- 🔧 TODO: explain why both fields are needed with a concrete example
hint: month-end close scenario — a transaction entered on May 1 may be
      dated April 30 for accounting purposes (the period it belongs to)
      posted_at records the exact moment it was committed to the ledger
-->

| Field | Type | Meaning |
|-------|------|---------|
| `transaction_date` | `DATE` | Accounting date — which period this entry belongs to |
| `posted_at` | `TIMESTAMPTZ` | System timestamp — when the record was written |
| `created_at` | `TIMESTAMPTZ` | Row creation timestamp (audit trail) |

## Analogy to Traditional Accounting Systems

<!-- 🔧 TODO: reference the SAP/Oracle equivalent field names
hint: SAP calls these Belegdatum (document date) and Buchungsdatum (posting date)
-->

## Consequences

- Balance queries use `transaction_date <= as_of` (not `posted_at`) to respect accounting periods
- Backdated entries are possible by design — access control to prevent abuse is deferred (TD-002)
- `posted_at` is set by the service layer at creation time; not user-supplied

## References

- [SAP Document Date vs Posting Date](https://help.sap.com/docs/)
- Implementation: `app/models/transaction.py`
- Related: ADR-005 (transaction status lifecycle)
