# Three-layer architecture: what belongs in a route vs. a service

> Date: 2026-06-15 | Goal: S7-3 (TD-022)
> Purpose: Why `create_account` and `get_audit_logs` were moved out of
> `app/api/v1/routes/*.py` and into `app/services/*.py`, with nothing about
> their logic changed — only *where* the logic lives.

---

## 1. The rule: api → services → models

This project follows a 3-layer convention (`CLAUDE.md` §9):

```
app/api/v1/routes/   →  app/services/   →  app/models/
   (HTTP)                (business logic)    (ORM / tables)
```

Before TD-022, every "create X" endpoint except `create_account` already
followed this: `create_transaction`, `create_user`, `create_currency`,
`create_exchange_rate` all live in `app/services/*.py`. `create_account` and
`get_audit_logs` were the odd ones out — they ran `db.add(...)`,
`await db.flush()`, and `log_action(...)` directly inside the route handler.

The inconsistency itself was the tech debt (TD-022): not a bug, but a
"why is this one different?" red flag for anyone reading the codebase.

---

## 2. What a route handler should and shouldn't do

A route handler's job is **HTTP plumbing only**:

- read path/query params, parse the request body (FastAPI + Pydantic do this)
- enforce auth (`Depends(...)` — `AdminUser`, `AuditorOrAdminUser`, etc.)
- call into the service layer
- shape the response / status code

It should **not** contain `db.add(...)`, `select(...)`, or business rules.
Those belong in the service layer, which knows nothing about HTTP.

Before (excerpt from `app/api/v1/routes/accounts.py`):

```python
@router.post("", response_model=AccountRead, status_code=201)
async def create_account(payload: AccountCreate, db: DbDep, current_user: AdminUser) -> Account:
    account = Account(code=payload.code, name=payload.name, ...)
    db.add(account)
    await db.flush()
    await db.refresh(account)
    after_value = {...}
    await log_action(db, user_id=current_user.id, entity_type="account", ...)
    return account
```

After:

```python
@router.post("", response_model=AccountRead, status_code=201)
async def create_account(payload: AccountCreate, db: DbDep, current_user: AdminUser) -> Account:
    return await account_service.create_account(db, payload, current_user)
```

The route now answers one question at a glance: "what HTTP operation is this,
and what does it delegate to?" The *how* moved to
`app/services/account_service.py`.

---

## 3. Why this matters in practice

**a) Unit-testability without HTTP.**
`tests/test_transactions.py` calls `create_transaction(db_session, payload, user_id=...)`
directly — no `async_client`, no ASGI transport, no testcontainers HTTP layer.
That's only possible because the logic lives in the service layer and only
needs an `AsyncSession`. If the same logic were inside the route handler, the
*only* way to exercise it would be through a full HTTP request.

**b) Reusability.**
A service function only needs `db` (and whatever plain arguments it declares).
It can be called from another route, a CLI script, a background job, or a
test — none of which have an HTTP request/response cycle. Logic trapped
inside a route handler can only ever be reached via that one endpoint.

**c) Consistency lowers cognitive load.**
Once a reader knows "business logic is always in `services/`", they can find
any piece of logic without guessing whether *this particular* endpoint is an
exception.

---

## 4. PHP/MVC comparison: Fat Controller → Skinny Controller

This is the same refactor as the classic "Fat Controller, Skinny Model"
anti-pattern fix:

```php
// Before — Fat Controller
class AccountController {
    public function create(Request $request) {
        $stmt = $pdo->prepare("INSERT INTO accounts (...) VALUES (...)");
        $stmt->execute([...]);
        $this->insertAuditLog($pdo, $request->user()->id, 'account', ...);
        return response()->json([...], 201);
    }
}

// After — Skinny Controller, logic in a Service
class AccountController {
    public function create(Request $request) {
        $account = $this->accountService->create($request->validated(), $request->user());
        return response()->json($account, 201);
    }
}
```

Same idea, different language: the Controller (≈ FastAPI route) becomes a
thin adapter between HTTP and the Service, which is where the actual work —
and the actual tests — live.

---

## 5. This was a behavior-preserving refactor

No logic changed — only its location. The existing HTTP-level tests
(`tests/test_accounts.py`, `tests/test_audit_log.py`,
`tests/test_audit_logs_endpoint.py`) act as regression tests: if they still
pass after the move, the extraction was correct. This is a useful general
pattern — "move, then verify with existing tests" — for low-risk refactors
distinct from changes that alter behavior (like TD-019's exception handling
or TD-031's TOCTOU fix, which *do* change what gets returned).

---

## Related documents

- `app/services/account_service.py`, `app/services/audit_service.py` (`list_audit_logs`)
- `app/api/v1/routes/accounts.py`, `app/api/v1/routes/audit_logs.py`
- `docs/tech-debt.md` — TD-022 (also references TD-008, the related
  repository-layer-separation debt that this does *not* address)
- `CLAUDE.md` §9 — File Placement Notes (3-layer rule)
