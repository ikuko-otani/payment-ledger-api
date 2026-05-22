# S3-5: Role-Based Access Control (admin / auditor)

**Date**: 2026-05-22
**Branch**: `feature/s3-5-role-based-access-control`
**Sprint**: S3 — JWT Authentication + Role-Based Access Control

---

## Goal Overview

Implemented role-based access control (RBAC) for all API endpoints.
Key additions:

- `app/core/deps.py`: `is_active` check in `get_current_user`; `require_admin` and
  `require_auditor_or_admin` dependencies; `AdminUser` and `AuditorOrAdminUser` type aliases
- `app/api/v1/routes/accounts.py`: POST → `AdminUser`, GET → `AuditorOrAdminUser`
- `app/api/v1/routes/transactions.py`: POST → `AdminUser`, GET → `AuditorOrAdminUser`
- `tests/conftest.py`: `auditor_client` fixture added alongside existing `async_client`
- `tests/test_rbac.py`: 12 RBAC integration tests (accounts, transactions, is_active, unauth)

---

## Implementation Notes

### Files created / edited

| File | Change |
|------|--------|
| `app/core/deps.py` | EDIT — `is_active` check; `require_admin`; `require_auditor_or_admin`; `AdminUser`; `AuditorOrAdminUser` |
| `app/api/v1/routes/accounts.py` | EDIT — POST uses `AdminUser`, GET uses `AuditorOrAdminUser` |
| `app/api/v1/routes/transactions.py` | EDIT — POST uses `AdminUser`, GET uses `AuditorOrAdminUser` |
| `tests/conftest.py` | EDIT — `auditor_client` fixture added |
| `tests/test_rbac.py` | NEW — 12 integration tests for RBAC |

---

## Key Concepts

### Depends() nesting: separating authentication from authorization

```python
async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin role required")
    return current_user

AdminUser = Annotated[User, Depends(require_admin)]
```

`require_admin` does not duplicate JWT logic — it delegates "who is this user?" entirely
to `get_current_user` via `Depends(get_current_user)`. FastAPI resolves the dependency
graph: when a handler declares `AdminUser`, FastAPI first resolves `get_current_user`
(JWT validation + DB lookup), then passes the result to `require_admin` (role check).

This is analogous to PHP middleware chains but scoped per-parameter rather than per-route,
giving finer control: a single router can mix `AdminUser` and `AuditorOrAdminUser` handlers.

### 401 vs 403: the RFC 9110 distinction

| Status | Meaning | When to use |
|--------|---------|-------------|
| 401 | "Who are you?" — authentication failed or missing | No token, expired token, invalid token, `is_active=False` |
| 403 | "I know who you are, but you can't do this" — authorization failed | Valid token, wrong role |

The `is_active=False` case is **401, not 403**. A deactivated account means the system
can no longer trust the authentication assertion — the identity check itself fails.
Using `credentials_exception` (the same exception as a bad token) is intentional:
it prevents an attacker from distinguishing "account deactivated" from "token invalid."

### is_active check placement in get_current_user

```python
async def get_current_user(...) -> User:
    ...
    user = user_result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise credentials_exception  # 401, not 403
    return user
```

The check lives in `get_current_user` — the single point that all protected endpoints
pass through. Adding it here means every downstream dependency (`require_admin`,
`require_auditor_or_admin`, `CurrentUser`) automatically inherits the check. There is no
need to repeat it in each role-checking function.

⚠️ A common mistake: forgetting `return user` after the `is_active` check. If omitted,
the function returns `None` implicitly for active users, causing a runtime error on the
first real request. mypy catches this as "Missing return statement."

### Side-effect dependencies: the _ prefix convention

```python
async def list_accounts(db: DbDep, _current_user: AuditorOrAdminUser) -> list[Account]:
    ...  # _current_user is never referenced in the body

async def post_transaction(
    payload: TransactionCreate,
    db: DbDep,
    _: IdempotencyDep,       # return value is None; the check is the side effect
    _current_user: AdminUser, # return value is User; the role check is the side effect
) -> Transaction:
    ...
```

FastAPI executes **all** `Depends()` in the function signature regardless of whether the
handler body uses the return value. The `_` prefix (single underscore) on a parameter name
signals "intentionally unused value." Linters (ruff, pylint) skip unused-variable warnings
for `_`-prefixed names.

Removing `_current_user` or `_: IdempotencyDep` would silently remove the security check,
not just the variable binding. The parameter declaration _is_ the security check.

### FastAPI dependency override propagation in tests

Overriding `get_current_user` in `dependency_overrides` propagates to all nested
dependencies automatically:

```python
# conftest.py
fastapi_app.dependency_overrides[get_current_user] = override_get_current_user
```

When `auditor_client` overrides `get_current_user` to return a `UserRole.AUDITOR` user,
`require_admin` (which calls `Depends(get_current_user)`) receives the overridden user —
and correctly raises 403 for AUDITOR. No separate override for `require_admin` is needed.

This is the key advantage of FastAPI's DI graph over middleware: the override is surgical
(per-function, per-test) rather than global (process-wide).

### Fixture design for RBAC testing

Three fixtures cover all test scenarios:

| Fixture | get_current_user | Role | Purpose |
|---------|-----------------|------|---------|
| `async_client` | mocked → ADMIN | ADMIN | Business logic + admin-only endpoint tests |
| `auditor_client` | mocked → AUDITOR | AUDITOR | RBAC enforcement tests (expect 403 on writes) |
| `unauthed_client` | real JWT validation | depends on DB | Auth flow + `is_active=False` tests |

For the `is_active=False` test, `unauthed_client` and `db_session` are combined:
register a user via HTTP, obtain a token, deactivate via `db_session.execute(update(...))`,
then call an endpoint with the now-invalid token.

The `db_session` and the HTTP client's session both use the same `engine` fixture (same
underlying PostgreSQL container), so the `db_session.commit()` is visible to the next
HTTP request.

### RBAC vs ABAC

This implementation uses RBAC (Role-Based Access Control): permission is derived entirely
from the user's role (`admin` or `auditor`). The alternative, ABAC (Attribute-Based Access
Control), would grant permission based on resource attributes — for example, "the account
owner can read their own balance, but not others'."

RBAC was chosen because the ledger has a simple two-role boundary. ABAC would require
passing resource IDs into the dependency and querying ownership, adding complexity not
justified by the current requirements. If per-account ownership is needed in a future sprint,
the `require_account_owner` dependency pattern would follow the same nesting approach.

---

## Key takeaways

**What did I learn?**

I learned that FastAPI's `Depends()` parameters serve two distinct purposes: providing a
value to the handler body, and executing side effects (auth checks, idempotency checks).
The `_` prefix convention was new to me as a formal signal to linters; I had treated it
as informal style before. Understanding that removing a `_`-prefixed parameter silently
removes a security check changed how I read route handler signatures.

I learned the precise RFC 9110 distinction between 401 and 403, and why `is_active=False`
belongs in the 401 category. The reasoning — "the identity assertion itself is no longer
trustworthy" — is more principled than "return whichever code feels right."

I learned that `dependency_overrides` for `get_current_user` propagates automatically to
all downstream `Depends()` calls. I had expected to need a separate override for
`require_admin`, but the DI graph resolution handles it transparently.

**What would I do differently?**

I would add `return user` as the very last line of `get_current_user` before writing the
`is_active` check, not after. The missing `return` caused a runtime failure that mypy
would have caught earlier if I had run it immediately after the edit.

**What surprised me?**

The fact that `_: IdempotencyDep` (a single underscore, not `_something`) is valid Python
syntax that FastAPI fully respects was surprising. I initially read it as a typo. The
combination of "idiomatic Python throwaway name" and "FastAPI dependency injection" creates
a pattern that looks wrong at first glance but is exactly correct.

**What is worth remembering for future goals?**

- `require_admin(current_user: User = Depends(get_current_user))` — never duplicate JWT
  logic in role-checking functions; always nest via `Depends`.
- `is_active=False` → 401 (auth failure), role mismatch → 403 (authz failure). The
  reason matters, not just the choice.
- Overriding `get_current_user` in `dependency_overrides` propagates to all nested
  `Depends(get_current_user)` calls automatically.
- A `_`-prefixed parameter in a FastAPI handler is not dead code — it declares a
  side-effect dependency. Removing it removes the security check.
- After adding an `if not condition: raise` guard, always verify that the happy-path
  `return` statement still exists. mypy is the fastest way to catch the omission.
