# SQLAlchemy: `MissingGreenlet` — Lazy Load on Relationship

## Date
2026-05-07

## Problem

Calling `POST /api/v1/transactions` via Swagger UI returns a 500 error during response serialization:

```
fastapi.exceptions.ResponseValidationError: 1 validation error:
  {
    'type': 'get_attribute_error',
    'loc': ('response', 'entries'),
    'msg': "Error extracting attribute: MissingGreenlet: greenlet_spawn has not been called;
            can't call await_only() here. Was IO attempted in an unexpected place?
            (Background on this error at: https://sqlalche.me/e/20/xd2s)",
    'input': <Transaction id=... date=2026-05-07 amount=1000.0000>,
    'ctx': {'error': "MissingGreenlet: ..."}
  }
```

Endpoint: `POST /api/v1/transactions` (`app/api/v1/routes/transactions.py`)

## Root Cause

`db.refresh(transaction)` only reloads scalar columns (`id`, `date`, `amount`, etc.).
The `entries` relationship remains in a **lazy-load** state — no DB query has been issued for it.

When FastAPI serializes the response, it accesses `transaction.entries`, but by that point the `AsyncSession` is already closed, triggering the `MissingGreenlet` error.

```
db.refresh(transaction)
  ↓
Scalar columns are refreshed
  ↓
entries relationship stays lazy (not loaded)
  ↓
FastAPI accesses transaction.entries during serialization
  ↓
AsyncSession is closed → MissingGreenlet 💥
```

### Why lazy load does not work with AsyncSession

SQLAlchemy's `AsyncSession` prohibits implicit IO (lazy loading).
Accessing a relationship attribute outside a session context raises this error because the greenlet context no longer exists.

## Fix

Replace `db.refresh()` with an explicit eager load using `selectinload`:

```python
# Before (❌ entries remains lazy)
await db.refresh(transaction)
return transaction

# After (✅ entries eagerly loaded within AsyncSession)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

result = await db.execute(
    select(Transaction)
    .where(Transaction.id == transaction.id)
    .options(selectinload(Transaction.entries))
)
return result.scalar_one()
```

## Verification

```bash
git pull origin feature/s1-2-double-entry-db-constraints
docker compose restart api
# → Confirm "Application startup complete." appears
```

Then re-run `POST /api/v1/transactions` via Swagger UI and confirm the response includes the `entries` field.

## Lesson Learned

| Approach | Usable? | Notes |
|---|---|---|
| `db.refresh(obj)` | ⚠️ Partial | Reloads scalar columns only; relationships are not reloaded |
| Lazy load (attribute access) | ❌ No | Raises MissingGreenlet outside AsyncSession |
| `selectinload` / `joinedload` | ✅ Recommended | Use `select().options(selectinload(...))` for explicit eager loading |
| `AsyncSession.refresh(obj, attribute_names=[...])` | ✅ Yes | Alternative when reloading specific attributes only |

## References

- [SQLAlchemy: Preventing Implicit IO — Asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#preventing-implicit-io-when-using-asyncsession)
- [SQLAlchemy error code xd2s](https://sqlalche.me/e/20/xd2s)
- [SQLAlchemy: selectinload](https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html#select-in-loading)
