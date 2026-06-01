# S4-6: GET /ledger + GET /audit-logs Endpoints

Date: 2026-06-01
Branch: feature/s4-6-get-ledger-get-audit-logs

---

## What We Built

Implemented two read endpoints:

- `GET /ledger` — dynamic filtering over entries+transactions with offset pagination (accessible to all authenticated users)
- `GET /audit-logs` — admin-only audit log viewer with dynamic filtering

### Files changed

| File | Change |
|------|--------|
| `app/schemas/ledger.py` | New — `TransactionSummary` + `LedgerEntryRead` |
| `app/schemas/audit_log.py` | New — `AuditLogRead` |
| `app/services/ledger_service.py` | New — `get_ledger_entries()` with JOIN + `contains_eager` + dynamic WHERE |
| `app/api/v1/routes/ledger.py` | New — `GET /ledger` route |
| `app/api/v1/routes/audit_logs.py` | New — `GET /audit-logs` route (admin only) |
| `app/api/v1/router.py` | Edit — include both new routers |
| `tests/test_ledger.py` | New — period/currency/account_id filter + pagination tests |
| `tests/test_audit_logs_endpoint.py` | New — admin access + auditor 403 + filter + pagination tests |

---

## Step C Walkthrough

### Dynamic WHERE pattern

The central pattern of this goal: accumulate conditions in a list and unpack into `.where()`.

```python
filters = []
if from_date is not None:
    filters.append(Transaction.transaction_date >= from_date)
if to_date is not None:
    filters.append(Transaction.transaction_date <= to_date)
if account_id is not None:
    filters.append(Entry.account_id == account_id)
if currency_code is not None:
    filters.append(Entry.currency == currency_code)

stmt = select(Entry).where(*filters)
```

If `filters` is empty, `.where(*[])` is a no-op and all rows are returned.
This avoids string concatenation and keeps each condition isolated and readable.

### `contains_eager` for JOIN + relationship loading

Since `GET /ledger` needs to filter by `Transaction.transaction_date` (a column on the joined table),
an explicit JOIN is required. `contains_eager` tells SQLAlchemy to reuse that JOIN result to
populate the `Entry.transaction` relationship — avoiding a second SELECT that `selectinload` would issue.

```python
stmt = (
    select(Entry)
    .join(Entry.transaction)                        # explicit JOIN for WHERE filtering
    .options(contains_eager(Entry.transaction))     # reuse JOIN data for relationship
    .where(*filters)
    .order_by(Transaction.transaction_date.desc(), Entry.id)
    .offset(offset)
    .limit(limit)
)
result = await db.execute(stmt)
return list(result.scalars().unique().all())        # .unique() required with contains_eager
```

| Strategy | Queries issued | When to use |
|----------|---------------|-------------|
| `lazy` (default) | N+1 | Small scale, simple access |
| `selectinload` | 2 (main + related) | Batch loading without JOIN |
| `joinedload` | 1 (LEFT OUTER JOIN) | Relationship loading without filtering |
| `contains_eager` | 1 (reuses existing JOIN) | Already joining for WHERE, want to load too |

### Nested Pydantic schema

`transaction_date` lives on `Transaction`, not `Entry`. Pydantic resolves this automatically
when `from_attributes = True` and the relationship is eagerly loaded:

```python
class TransactionSummary(BaseModel):
    transaction_date: date
    description: str
    status: TransactionStatus
    model_config = {"from_attributes": True}

class LedgerEntryRead(BaseModel):
    id: uuid.UUID
    ...
    transaction: TransactionSummary     # entry.transaction.transaction_date resolved here
    model_config = {"from_attributes": True}
```

### Admin-only enforcement for audit-logs

`GET /audit-logs` uses `Depends(require_admin)` via the `AdminUser` type alias.
Auditor role receives 403. This is enforced by `require_admin()` in `app/core/deps.py`
which checks `current_user.role != UserRole.ADMIN`.

### Swagger UI limitation discovered

The `POST /api/v1/auth/login` endpoint accepts JSON (`{"email": ..., "password": ...}`),
but Swagger UI's Authorize dialog sends OAuth2 standard form data with `username` field.
The mismatch causes 422 on every Authorize attempt.
Workaround: obtain the token via `POST /api/v1/auth/login` "Try it out" in Swagger,
then use PowerShell `Invoke-RestMethod` with `Authorization: Bearer <token>` header for manual verification.

---

## Key Takeaways

### What did I learn?

I learned the dynamic WHERE pattern using a condition list and `.where(*filters)` — a clean,
injection-safe way to build optional query filters that is widely applicable in SQLAlchemy.

I learned the difference between `selectinload`, `joinedload`, and `contains_eager`.
When a JOIN is already needed for filtering, `contains_eager` avoids a redundant second query
by reusing the data already fetched. The `.unique()` call after `scalars()` is required
when `contains_eager` is in use because the JOIN can produce duplicate ORM object references.

I also learned that Pydantic with `from_attributes = True` resolves nested relationships
automatically — nesting `TransactionSummary` inside `LedgerEntryRead` was enough to expose
`transaction_date` in the response without any manual field mapping.

### What would I do differently?

I would think more carefully about test data coverage from the start.
My initial currency filter test only tested against a non-existent currency code,
which would pass even without the filter implemented (trivially empty result).
A meaningful filter test requires data of multiple values to exist, so the filter
has something real to exclude. The fix was to add a second transaction with EUR
to create a genuinely mixed dataset.

### What surprised me?

Python attribute names are case-sensitive, and `Entry.Transaction` (capital T) refers to
a non-existent class attribute while `Entry.transaction` (lowercase) is the correct
relationship name. The typo would have caused a runtime `AttributeError` rather than
a static analysis error, making it easy to miss without running the code.

The Swagger UI Authorize button being fundamentally broken for this app was also unexpected.
The root cause — OAuth2 password flow sends form data, our endpoint expects JSON — is a
design choice that has a real UX cost during manual testing.

### What is worth remembering for future goals?

- Dynamic WHERE pattern: `filters = []; if x: filters.append(...); stmt.where(*filters)`
- `contains_eager` requires both `.join()` AND `.options(contains_eager(...))` together
- `.unique()` is required after `scalars()` when using `contains_eager`
- Offset pagination limitation: concurrent inserts can shift rows across pages; cursor-based
  pagination is safer for append-heavy tables like audit logs (registered as tech debt)
- Test design: a filter test without mixed-value data cannot prove the filter excludes anything
- Admin-only for audit logs: full operation history reveals personal data, minimum privilege applies
