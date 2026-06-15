# Audit log pattern: app-layer `log_action`, same-transaction atomicity, and the self-reference edge case

> Date: 2026-06-16 | Context: TD-021 (PR #71)
> Purpose: How this project records "who did what, to which row, when" —
> and what TD-021 fixed (`POST /currencies`, `POST /exchange-rates`,
> `POST /users` were silently missing this).

---

## 1. What an audit log is for

In systems that handle money or configuration data, every write
(create/update/delete) is typically recorded in a separate append-only
table: **who** did it, **what** kind of row, **which** row, **when**, and
the before/after values. This is the `audit_logs` table here.

Oracle/PL-SQL comparison: the same thing is often done with a `BEFORE/AFTER`
trigger that inserts into an `AUDIT_LOG` table. This project does **not**
use a DB trigger — it calls a function explicitly from the service layer.

---

## 2. `log_action`: app-layer write, same transaction

```python
# app/services/audit_service.py (unchanged)
async def log_action(
    db: AsyncSession,
    user_id: uuid.UUID,
    entity_type: str,    # "currency", "user", "exchange_rate", ...
    entity_id: uuid.UUID,
    action: str,         # "create", ...
    before: dict | None,
    after: dict | None,
) -> None:
    db.add(AuditLog(...))   # no flush/commit here
```

`log_action` only calls `db.add(...)`. It does **not** flush or commit.
That's the key design point: as long as it's called with the **same
`AsyncSession`** as the main operation, the audit row and the main row
are written in the same transaction. If the main `db.flush()` (or the
final `commit()` in `get_db`) fails, both roll back together — you can
never end up with an audit row for a row that doesn't exist, or vice versa.

PHP/PDO equivalent:

```php
$pdo->beginTransaction();
$stmt1->execute([...]);              // INSERT INTO currencies
$stmt2->execute([$userId, 'currency', $newId, 'create', ...]); // INSERT INTO audit_logs
$pdo->commit();                      // both succeed or both roll back
```

---

## 3. TD-021: which endpoints were missing it, and the fix

`create_account` and `create_transaction` already called `log_action`.
Three "admin write" operations did not:

| Service function | File | Actor used for `user_id` |
|---|---|---|
| `create_currency` | `app/services/currency_service.py` | new `current_user: User` param, threaded from the route's `AdminUser` |
| `create_exchange_rate` | `app/services/currency_service.py` | existing `created_by: User` param (no signature change needed) |
| `create_user` | `app/services/user_service.py` | the newly created user itself (see §4) |

All three follow the exact shape already established by
`create_account` (`app/services/account_service.py`):

```python
db.add(row)
await db.flush()
await db.refresh(row)

after_value = {... "id": str(row.id), ...}   # JSON-serializable snapshot
await log_action(
    db,
    user_id=<actor>.id,
    entity_type="<type>",
    entity_id=row.id,
    action="create",
    before=None,
    after=after_value,
)
return row
```

`create_currency` needed a route change too, since its `AdminUser` arg
was previously unused (`_current_user`, underscore convention for
"intentionally unused"):

```python
# Before
async def post_currency(payload: CurrencyCreate, db: DbDep, _current_user: AdminUser) -> Currency:
    return await create_currency(db, payload)

# After
async def post_currency(payload: CurrencyCreate, db: DbDep, current_user: AdminUser) -> Currency:
    return await create_currency(db, payload, current_user)
```

`create_exchange_rate` already took `created_by: User` for
`exchange_rates.created_by_id`, so it could reuse that value as the
audit actor with no caller-side change.

---

## 4. The self-reference edge case: `POST /users`

`POST /users` (self-registration) is **unauthenticated** — there is no
"current user" to blame for the write. The chosen design: the newly
created user is recorded as the actor for its own creation row.

```python
# app/services/user_service.py
await log_action(
    db,
    user_id=user.id,     # actor == the row being created
    entity_type="user",
    entity_id=user.id,   # subject == the row being created
    action="create",
    before=None,
    after=after_value,
)
```

This is called **after** `await db.refresh(user)`, so `user.id` is a
real, flushed primary key by the time `log_action` runs — the
`audit_logs.user_id → users.id` foreign key (within the same
transaction) is satisfied.

Alternative considered: a fixed "system"/"anonymous" user row. Rejected
because "the actor of a self-registration is the registrant" is more
semantically accurate, and avoids needing a synthetic seed row.

---

## 5. Tests added

`tests/test_audit_log.py` gained three tests, all following the existing
`test_create_account_writes_audit_log` shape: POST via `async_client`,
then query `audit_logs` directly via `db_session`.

- `test_create_currency_writes_audit_log` — unfiltered `select(AuditLog)`,
  `len(logs) == 1` (only one row created in this test).
- `test_create_exchange_rate_writes_audit_log` — filters
  `.where(AuditLog.entity_type == "exchange_rate")`, because the test
  also creates two currencies first (each now also writes an
  `entity_type="currency"` row).
- `test_register_user_writes_audit_log` — filters by
  `entity_type == "user"` and additionally asserts
  `logs[0].user_id == logs[0].entity_id == <new user id>`, to pin down
  the self-reference behavior from §4.

No fixture changes were needed: `tests/conftest.py`'s `async_client`
already seeds a real `users` row matching `override_get_current_user`'s
id (`_FIXTURE_ADMIN_ID`), specifically so `audit_logs.user_id`'s FK is
satisfied — this was already in place for `create_account`'s audit call.

---

## 6. Interview-relevant points

1. **App-layer vs. DB-trigger audit logging** — triggers guarantee no
   write is ever missed (which is exactly what TD-021 was: a missed
   app-layer call), but scatter logic outside the codebase and are harder
   to unit-test. App-layer logging is more visible/testable but relies on
   every write path remembering to call it.
2. **Why `log_action` doesn't flush/commit itself** — atomicity. Same
   session = same transaction = all-or-nothing with the main write.
3. **The self-reference design (`user_id == entity_id`)** — a concrete
   example of "who is the actor when there is no authenticated actor?",
   and why a synthetic system-user row was rejected in favor of
   self-reference.

---

## Related documents

- `app/services/audit_service.py` — `log_action`, `list_audit_logs`
- `app/services/account_service.py` — the original pattern this PR copied
- [sqlalchemy-async-session-commit-pattern.md](sqlalchemy-async-session-commit-pattern.md) — flush vs. commit, why same-session matters
- [three-layer-architecture-route-vs-service.md](three-layer-architecture-route-vs-service.md) — why this logic lives in `services/`, not the route
- `docs/tech-debt.md` — TD-021 (Resolved)
