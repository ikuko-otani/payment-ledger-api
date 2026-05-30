# S4-5: AuditLog Write Logic

Date: 2026-05-30
Branch: feature/s4-5-audit-log-write-logic

---

## What We Built

Implemented audit logging for all mutation endpoints by integrating `log_action()` into the same `AsyncSession` as the main operation.

### Files changed

| File | Change |
|---|---|
| `app/services/audit_service.py` | New — `log_action()` function |
| `app/services/transaction_service.py` | Added `user_id` param, `log_action()` call |
| `app/api/v1/routes/transactions.py` | Pass `current_user.id` to service |
| `app/api/v1/routes/accounts.py` | Call `log_action()` directly in route |
| `tests/conftest.py` | Seed real User in `async_client` fixture for FK constraint |
| `tests/test_audit_log.py` | New — 3 integration tests |

---

## Step C Walkthrough

### Key implementation pattern

```python
# audit_service.py — cross-cutting concern, session.add() only
async def log_action(db, user_id, entity_type, entity_id, action, before, after):
    db.add(AuditLog(user_id=user_id, entity_type=entity_type, ...))
    # no flush here — caller's commit/flush handles it atomically
```

```python
# transaction_service.py — log_action() called after flush, before return
loaded = tx_result.scalar_one()
after_value = {
    "id": str(loaded.id),
    "description": loaded.description,
    "status": loaded.status.value,
    "transaction_date": str(loaded.transaction_date),
}
await log_action(db, user_id=user_id, entity_type="transaction", ...)
return loaded
```

### Why after_value uses str() and .value

`loaded.status` is a Python Enum and `loaded.transaction_date` is a `datetime.date` object.
PostgreSQL's JSONB driver does not auto-convert these types, so explicit conversion is needed:
- Enum → `.value` (e.g. `"posted"`)
- date / UUID → `str()`

### The conftest.py FK problem

`async_client` fixture previously returned a mock User with `id=uuid.uuid4()` (random,
not in DB). Adding audit logging caused FK violations because `audit_logs.user_id` references
`users.id`. Fixed by seeding a real User row with a fixed UUID (`_FIXTURE_ADMIN_ID`) inside
the `async_client` fixture setup, after `clean_db` TRUNCATE runs.

```python
_FIXTURE_ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# inside async_client fixture:
async with session_factory() as seed_session:
    seed_session.add(User(id=_FIXTURE_ADMIN_ID, ...))
    await seed_session.commit()
```

### The atomicity test and db.flush()

`log_action()` only calls `db.add()` — no SQL is sent to PostgreSQL at that point.
SQL is sent only on `flush()` or `commit()`. In the atomicity test, calling `create_transaction()`
with a non-existent `user_id` does NOT raise immediately because `log_action()` never flushes.
The FK violation only fires when `await db_session.flush()` is called explicitly:

```python
with pytest.raises((IntegrityError, Exception)):
    await create_transaction(db_session, payload, user_id=nonexistent_user_id)
    await db_session.flush()  # ← FK check fires here
```

In production, `get_db` calls `await session.commit()` after the route handler returns,
which flushes internally — so the FK check happens automatically.

### SQLAlchemy flush / commit / rollback summary

| Operation | SQL sent | Committed | Reversible |
|---|---|---|---|
| `db.add()` | No | No | — |
| `flush()` | Yes | No | Yes (rollback) |
| `commit()` | Yes (flushes first) | Yes | No |
| `rollback()` | Yes (ROLLBACK) | No | Clears all unflushed |

Git analogy: `flush()` = commit on a feature branch (local, not merged); `commit()` = merge to main.

---

## Key Takeaways

### What did I learn?

I learned how SQLAlchemy's unit-of-work pattern separates `add()`, `flush()`, and `commit()`.
Before this goal, I understood that commit() was the final step, but I didn't have a clear
mental model of when SQL is actually sent to PostgreSQL. The FK violation test made this
concrete: `db.add()` is purely in-memory, `flush()` sends SQL without committing, and the
FK constraint fires at flush time — not at add() time.

I also learned that audit logging is most naturally implemented as a cross-cutting concern
in its own service module (`audit_service.py`), with the dependency direction flowing one way:
business services → audit service. Reversing this would create circular imports.

### What would I do differently?

I would identify the `async_client` FK problem earlier — at Step A scope confirmation —
rather than discovering it when tests fail. The pattern "mock user returns random UUID not
in DB" is a common trap when FK constraints are added to tables downstream of users.

### What surprised me?

The ruff E402 error from placing `_FIXTURE_ADMIN_ID` between import blocks. In PHP, constants
can be declared anywhere at file scope without affecting import ordering. Python's linter
enforces that no non-import statements appear before imports are complete.

The Git / database transaction analogy also helped solidify my understanding:
`flush()` = commit on a feature branch (visible only within the branch),
`commit()` = merge to main (visible to all sessions).

### What is worth remembering for future goals?

- `db.add()` is in-memory only. FK constraints fire at `flush()` / `commit()`, not at `add()`.
- When adding audit logging or any FK-referencing table, check whether existing test fixtures
  seed the referenced row into the DB. Mock objects that don't persist to DB will break FK constraints.
- Atomicity of audit + main operation is guaranteed by sharing the same `AsyncSession`.
  Separate sessions = ghost logs or lost logs — both are critical audit failures.
- `before_value` must be captured BEFORE the UPDATE executes. After updating, both before and
  after would return the same value. (Relevant for S4-6 and future UPDATE operations.)
