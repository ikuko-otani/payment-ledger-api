# S2-4: TD-001 Debug Log — Missing commit in test fixture

> Date: 2026-05-12 | Goal: S2-4 | support_level: guided  
> Related note: [concepts/sqlalchemy-async-session-commit-pattern.md](./concepts/sqlalchemy-async-session-commit-pattern.md)

---

## Background

During S2-2, the following two tests were left failing after implementing `GET /transactions`.

```
FAILED tests/test_transactions_http.py::test_get_transactions_returns_list_shape
FAILED tests/test_transactions_http.py::test_post_then_get_shows_persisted_record
```

Registered as TD-001 and deferred to S2-4 for root-cause investigation and fix.

---

## Symptoms

### test_get_transactions_returns_list_shape

After POSTing a transaction, a subsequent GET /transactions returned an empty list `[]`.

```
AssertionError: assert 0 >= 1
```

### test_post_then_get_shows_persisted_record

The ID returned from POST was not present in the list returned by GET /transactions.

```
AssertionError: assert created_id in ids_in_list
```

---

## Initial hypotheses (as of S2-2)

Three hypotheses were on the table.

| Hypothesis | Description |
|------|------|
| A | `async_client` and `db_session` share the same engine but use separate sessions — a visibility problem |
| B | Missing `selectinload` — entries are lazy-loaded and cause `MissingGreenletError` during serialization |
| C | Fixture scope mismatch — session-scoped and function-scoped fixtures interacting incorrectly |

B and C were ruled out by the test output (plain `AssertionError`, no `MissingGreenletError`).  
Hypothesis A remained the most likely candidate but was not confirmed until S2-4.

---

## Investigation (S2-4)

### Step 1 — Confirm that POST alone works correctly

`test_post_transactions_returns_201_with_id` was PASSING.  
The same `async_client` fixture posted a transaction and received a 201 response with a valid `id`.

→ **The service layer, schema layer, and routing are all correct. The problem is cross-request persistence.**

### Step 2 — Decompose "POST succeeds but GET sees nothing"

Only two root causes can produce this symptom:

1. POST wrote data to the DB but **it was never committed** (invisible to other sessions)
2. GET is **hitting a different DB or schema**

Since both fixtures share the same engine, cause 2 is ruled out.  
→ Suspect: **flush was called but commit was not.**

### Step 3 — Compare production `get_db` with `override_get_db`

`app/db/session.py` (production `get_db`):

```python
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()   # ← present
        except Exception:
            await session.rollback()
            raise
```

`tests/conftest.py` (`override_get_db` at the time):

```python
async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session
        # ← no commit, no rollback
```

**Difference found.** `override_get_db` never called `commit()`.

### Step 4 — Explain why `test_post_transactions_returns_201_with_id` was passing

`create_transaction` calls `flush()` twice, not `commit()`.  
`flush()` sends SQL to the DB but does not end the transaction.

```
Inside the POST request:
  session.flush()  → SQL reaches the DB (visible within the same session)
  FastAPI builds the 201 response  ← same session → data is visible ✅
  Handler returns
  ↓
  override_get_db teardown: async with exits → session.close() → rollback

Subsequent GET (new session):
  → DB has no committed data → empty list ❌
```

The POST test passed because the response was built **within the still-open session**.
The data was never durably persisted.

---

## Fix

Update `override_get_db` to mirror the production `get_db` pattern (two lines added).

```python
# tests/conftest.py (after fix)
async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        try:
            yield session
            await session.commit()    # ← added
        except Exception:
            await session.rollback()  # ← added
            raise
```

After this change, both `test_get_transactions_returns_list_shape` and
`test_post_then_get_shows_persisted_record` became PASSED.

---

## Lessons learned

> **Design principle:** A test's dependency override must faithfully reproduce the side effects
> of the production dependency — including transaction commit and rollback guarantees.

The root cause was that `override_get_db` did not replicate the commit behavior of production
`get_db`. This is a classic pitfall in FastAPI + SQLAlchemy test design.

Hypothesis A ("separate sessions = visibility problem") was indirectly correct, but the precise
cause was SQLAlchemy's fundamental transaction boundary rule: uncommitted data is not visible
across sessions.

---

## Related documents

- [concepts/sqlalchemy-async-session-commit-pattern.md](./concepts/sqlalchemy-async-session-commit-pattern.md)
  — General explanation of flush vs. commit and the dependency override design principle
- `app/db/session.py` — Production `get_db` implementation
- `tests/conftest.py` — Fixed `override_get_db`
