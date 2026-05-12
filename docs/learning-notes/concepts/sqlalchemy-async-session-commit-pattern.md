# SQLAlchemy async session — commit patterns and the dependency override principle

> Date: 2026-05-12 | Goals: S2-4 onwards  
> Purpose: Reference note for session lifecycle design and testing in FastAPI + SQLAlchemy 2.0 (async)

---

## 1. flush() vs. commit()

SQLAlchemy manages request processing through the **Unit of Work** pattern.
Changes accumulate in an in-memory Identity Map and are sent to the DB at flush or commit time.

| Operation | Sends SQL to DB | Ends the transaction | Visible to other sessions |
|---|:---:|:---:|:---:|
| `session.flush()` | ✅ | ❌ | ❌ |
| `session.commit()` | ✅ | ✅ | ✅ |
| `session.rollback()` | — | ✅ (discards) | — |

### What flush() is for

`flush()` synchronizes the in-memory cache with the DB within the **current transaction**.
Data is visible within the same session but not to any other connection.

Typical use cases:
- You need the DB-generated primary key of a newly inserted row before committing.
- Multiple INSERTs must be written in order to satisfy foreign key constraints mid-operation.

### What commit() is for

`commit()` finalizes the transaction, making all changes **visible to every connection**.
After commit, SQLAlchemy expires the Identity Map entries
(suppressed by `expire_on_commit=False` — see Section 5).

---

## 2. What happens when async with exits without a commit

```python
async with session_factory() as session:
    session.add(some_object)
    await session.flush()
    # ← what happens when the with block exits here?
```

When `async with AsyncSession(...)` exits, SQLAlchemy calls `session.close()` internally.
`close()` **rolls back any uncommitted transaction**.

```
open session
  → add / flush  → SQL reaches the DB (uncommitted)
  → with block exits → session.close() → rollback ← changes are lost
```

Without an explicit `commit()`, any changes are discarded when the context exits.

### PHP/PDO comparison

```php
$pdo->beginTransaction();
$stmt->execute([...]);
// ← what if the function returns here without committing?
// PHP implicitly rolls back when the script ends
$pdo->commit(); // ← this is required
```

The same principle applies in SQLAlchemy: **no explicit commit = rollback on context exit**.

---

## 3. Why the FastAPI get_db pattern needs try/yield/commit/except

```python
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session           # ← request handler runs here
            await session.commit()  # ← commit on normal exit
        except Exception:
            await session.rollback() # ← rollback on error
            raise
```

A `yield`-based FastAPI dependency behaves as a context manager around each request.

```
Request arrives
  → get_db creates a session and yields it
  → handler runs (e.g. create_transaction)
  → handler returns
  → control returns after yield → await session.commit()
  → response is sent to the client
```

If an exception is raised (including `HTTPException`), the `except` block rolls back.

---

## 4. Why the test override must mirror production get_db

```python
# ❌ Wrong — no commit
async def override_get_db():
    async with session_factory() as session:
        yield session
        # data is rolled back between requests

# ✅ Correct — same transaction guarantees as production
async def override_get_db():
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

**Why this matters:**  
If the test does not go through the same session lifecycle as production, a passing test
does not prove production correctness. TD-001 was exactly this case — `override_get_db`
did not commit, so POST returned 201 but the subsequent GET saw an empty DB.

> **Design principle:** A dependency override must reproduce not just the signature but also
> the side effects (transaction guarantees) of the production dependency.

---

## 5. Why expire_on_commit=False is required in async contexts (supplementary)

```python
async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

With the default `expire_on_commit=True`, object attributes are marked as expired after
a commit. The next attribute access triggers an additional SELECT — but in an async context,
the session may already be closed, causing `MissingGreenletError`.

`expire_on_commit=False` prevents this by keeping attribute values accessible after commit.  
See also: `docs/troubleshooting/sqlalchemy-missing-greenlet-lazy-load.md`

---

## Related documents

- [../s2-4-td001-fixture-debug.md](../s2-4-td001-fixture-debug.md)
  — Concrete investigation and fix record for TD-001
- `app/db/session.py` — Production `get_db` implementation
- `docs/troubleshooting/sqlalchemy-missing-greenlet-lazy-load.md` — MissingGreenletError details
