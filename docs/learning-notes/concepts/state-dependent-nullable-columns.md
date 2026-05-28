# State-Dependent Nullable Columns

**Date**: 2026-05-27  
**Context**: S4-3 — noticed that `transactions.posted_at` is `nullable=True` without a CHECK constraint

---

## Question

Why does `transactions.posted_at` not have a `NOT NULL` constraint at the DB level?  
Is `nullable=True` a bug or intentional?

---

## Answer

`posted_at` is nullable **by design**, not by mistake.

`TransactionStatus` has three states: `PENDING`, `POSTED`, `VOIDED`.  
`posted_at` represents "when the transaction transitioned to POSTED".  
A transaction in `PENDING` state has not been posted yet — `posted_at = NULL` is the
correct representation of that fact.

```
status = PENDING  →  posted_at = NULL           (not yet posted)
status = POSTED   →  posted_at = 2024-01-15 …   (timestamp of posting)
status = VOIDED   →  posted_at = NULL or original timestamp (implementation-dependent)
```

The Python type `Mapped[datetime | None]` and the DB constraint `nullable=True` are
intentionally aligned — the nullable at the DB level mirrors the Optional at the Python level.

---

## The More Rigorous Design: CHECK Constraint

PostgreSQL does not support conditional NOT NULL
(i.e., "NOT NULL only when another column equals a certain value").  
The correct way to express "if POSTED then posted_at must exist" is a CHECK constraint:

```sql
ALTER TABLE transactions
  ADD CONSTRAINT ck_posted_at_required_when_posted
  CHECK (status != 'posted' OR posted_at IS NOT NULL);
```

In SQLAlchemy (`__table_args__`):

```python
from sqlalchemy import CheckConstraint

class Transaction(Base):
    __table_args__ = (
        CheckConstraint(
            "status != 'posted' OR posted_at IS NOT NULL",
            name="ck_posted_at_required_when_posted",
        ),
    )
```

This constraint is absent in the current codebase — a tech debt item.  
The application layer (service always sets both `status=POSTED` and `posted_at` together)
enforces the rule at runtime, so there is no practical data integrity risk today.

---

## General Pattern: State-Dependent Nullable Columns

This is a common pattern in finite state machine (FSM) modelling.  
Columns that only carry meaning in a specific state are made nullable:

| Column | Meaningful when | NULL when |
|--------|----------------|-----------|
| `posted_at` | `status = POSTED` | `status = PENDING / VOIDED` |
| `voided_at` (hypothetical) | `status = VOIDED` | `status = PENDING / POSTED` |
| `shipped_at` (e-commerce) | `status = SHIPPED` | earlier states |

**Trade-off**: State-dependent nullable columns are simple to implement but shift
the integrity guarantee to the application layer. A CHECK constraint re-establishes
the DB as the final line of defence.

---

## Interview Relevance

> "How do you enforce data integrity across your stack?"

Good answer:
- **Pydantic** (API layer): shape validation, required fields
- **Service layer**: business rule validation (e.g., double-entry balance)
- **DB NOT NULL / UNIQUE / FK**: structural guarantees
- **DB CHECK constraints**: cross-column invariants (e.g., state-dependent fields)

The `posted_at` example is a concrete illustration of where a CHECK constraint
would strengthen the "DB as last line of defence" principle.

---

## Related

- `ARCHITECTURE.md` ADR-002 — Double-entry balance enforced at application layer + DB trigger
- `docs/tech-debt.md` — candidate for adding `ck_posted_at_required_when_posted`
