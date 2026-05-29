# S4-4: AuditLog Model + Alembic Migration

**Date**: 2026-05-29
**Branch**: `feature/s4-4-audit-log-model-migration`
**Goal**: Design and create the `audit_logs` table as the foundation for audit
logging. First use of the `users` FK introduced in S3.

---

## Step C Walkthrough

### Step C-1: AuditLog SQLAlchemy Model

Created `app/models/audit_log.py`.

Key design decisions:

**`__table_args__` — single-element tuple requires trailing comma**

```python
__table_args__ = (
    Index("ix_audit_logs_created_at", "created_at"),
)
```

The trailing comma is mandatory. Without it Python treats the parentheses
as grouping (not a tuple), causing a `ProgrammingError` at import time.

**`user_id` — `ondelete="RESTRICT"` instead of `CASCADE`**

```python
user_id: Mapped[uuid.UUID] = mapped_column(
    ForeignKey("users.id", ondelete="RESTRICT"),
    nullable=False,
    index=True,
)
```

`CASCADE` would delete all audit rows when the user is deleted, destroying
the audit trail. `RESTRICT` blocks the user delete instead, preserving
compliance records.

**`before_value` / `after_value` — `JSONB` from PostgreSQL dialect**

```python
from sqlalchemy.dialects.postgresql import JSONB

before_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
after_value:  Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
```

`JSONB` (binary storage) vs `JSON` (text storage):
- `JSONB` supports GIN indexes → efficient field-level queries
- `JSON` is stored as-is (text) → no field-level indexing

`before_value` is `nullable=True` because CREATE actions have no prior state.

**`created_at` — `server_default=func.now()`**

```python
created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now(),
    nullable=False,
)
```

`server_default=func.now()` sets the default at the DB level. The service
layer never needs to set this manually — the DB fills it at INSERT time.
This is different from `default=datetime.now` (Python-side default).

### Step C-2: Alembic Migration

```bash
docker compose up -d
uv run alembic revision --autogenerate -m "add_audit_logs_table"
```

autogenerate correctly detected `JSONB` from the PostgreSQL dialect:

```python
sa.Column('before_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
```

It also auto-created `ix_audit_logs_user_id` for the `index=True` on `user_id`
(in addition to `ix_audit_logs_created_at` from `__table_args__`).

### Step C-3: upgrade head + DB verification

```bash
uv run alembic upgrade head
docker compose exec db psql -U ledger_user -d ledger_db -c "\d audit_logs"
```

Confirmed: 8 columns, `jsonb` type for before/after, FK to `users`.

### Step C-4: ARCHITECTURE.md — ADR-008

Added ADR-008 documenting why JSONB was chosen over:
- Plain `JSON` (no GIN index support)
- Normalised snapshot table (migration required per new field)
- Event Sourcing (out of scope for MVP complexity)

### Step C-5: conftest.py — TRUNCATE list

Added `audit_logs` to the head of the TRUNCATE list (FK dependency order:
`audit_logs` references `users`, so it must be truncated before `users`).

```python
"TRUNCATE TABLE audit_logs, exchange_rates, entries, "
"transactions, accounts, users, currencies CASCADE"
```

### Step C-6: mypy / ruff / pytest — all green

No type errors. Existing 8 currency-conversion tests continued to pass.

---

## Key Takeaways

### What did I learn?

- The difference between `JSONB` and `JSON` in PostgreSQL is not just storage
  format — it determines whether GIN indexes and efficient field-level queries
  (`->>`, `@>`) are possible. I learned to import `JSONB` from
  `sqlalchemy.dialects.postgresql`, not from `sqlalchemy` itself.
- A single-element `__table_args__` tuple silently breaks without the trailing
  comma. The Python parser treats `(Index(...))` as grouped expression, not a
  tuple, which causes a runtime `ProgrammingError`.
- `server_default=func.now()` vs `default=datetime.now`: the former sets a DB-
  level default (SQL `now()` runs at INSERT), the latter sets a Python-level
  default (evaluated when the ORM object is created). For audit timestamps,
  the DB-level default is more reliable because it is immune to clock skew
  between application servers.
- `ondelete="RESTRICT"` on the `user_id` FK is the deliberate choice for audit
  logs: preserving records even when the user is removed is a compliance
  requirement, not a bug.

### What would I do differently?

- I would check `__table_args__` trailing comma earlier in the review process.
  It is easy to forget and the error only surfaces at import time, not during
  model definition.
- I would consider whether `action` and `entity_type` should be PostgreSQL
  ENUMs to get DB-level validation. Using `String` is more flexible but allows
  arbitrary values. For MVP this is fine; for production I would lock them down.

### What surprised me?

- autogenerate added `ix_audit_logs_user_id` automatically because `index=True`
  was set on the `user_id` column. I only explicitly defined `ix_audit_logs_created_at`
  in `__table_args__`. The autogenerated index name follows Alembic's naming
  convention (`ix_<table>_<column>`).
- The migration correctly used `postgresql.JSONB` (not `sa.JSON`) without any
  manual adjustment. SQLAlchemy's dialect introspection handled it automatically.

### What is worth remembering for future goals?

- **AuditLog is INSERT-only**: the application layer must never issue UPDATE or
  DELETE on `audit_logs`. In production, DB-level `REVOKE UPDATE, DELETE ON
  audit_logs FROM app_role` provides an additional safety net.
- **FK order in TRUNCATE matters**: tables that reference others via FK must
  appear before the referenced table in a `TRUNCATE ... CASCADE` statement,
  or `CASCADE` handles it — but being explicit avoids surprises.
- **JSONB is the right default for schema-agile snapshot columns**: when the
  shape of the snapshotted object may change over time, JSONB avoids the need
  for a migration to `audit_logs` every time a new field is added to the
  source entity.
- S4-5 will wire the AuditLog write calls into the service layer. The model
  and table are now in place; the integration is the next step.
