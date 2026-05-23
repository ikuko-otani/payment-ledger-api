# S3-6: Authenticated conftest.py Restructuring + Test Helpers

**Date**: 2026-05-23
**Branch**: `feature/s3-6-authenticated-conftest`
**Sprint**: S3 — JWT Authentication + Role-Based Access Control

---

## Goal Overview

Restructured `tests/conftest.py` to replace the `dependency_overrides[get_current_user]` bypass
pattern with real JWT-based authentication fixtures. Added:

- `_seed_user` / `_make_db_override` private helpers
- `admin_token` / `auditor_token` fixtures (function scope, real JWT)
- `authenticated_client(role)` factory fixture (AsyncExitStack pattern)
- `auditor_client` replaced with a token-based version (same fixture name)
- Two new DONE-condition tests in `test_rbac.py`

---

## Implementation Notes

### Files edited

| File | Change |
|------|--------|
| `tests/conftest.py` | Added helpers + fixtures; replaced `auditor_client` with token-based version |
| `tests/test_rbac.py` | Added `test_authenticated_admin_can_post_transaction` and `test_authenticated_auditor_cannot_post_transaction` |

### Fixture dependency graph

```
engine (function)
├── clean_db (autouse)
├── db_session
├── async_client          ← override-based; kept for non-auth tests
├── unauthed_client       ← no auth override; used for auth pipeline tests
├── admin_token           ← _seed_user + login → yields str
├── auditor_token         ← _seed_user + login → yields str
├── authenticated_client  ← factory; yields Callable[[str], AsyncClient]
└── auditor_client        ← _seed_user + login + header; yields AsyncClient
```

### Key design decisions

**1. Function scope for all token fixtures**

`clean_db` TRUNCATEs the `users` table before and after every test. Any session-scoped
user seeding would be invalidated on the next TRUNCATE. Function scope re-seeds the user
for every test, trading a small performance cost for reliable isolation.

**2. Direct DB INSERT instead of POST /api/v1/users**

`POST /api/v1/users` requires `AdminUser`. To create an admin user, we would need another
admin user — a bootstrap chicken-and-egg problem. Seeding directly via `async_sessionmaker`
sidesteps the dependency entirely.

**3. Factory fixture pattern for `authenticated_client`**

pytest fixtures cannot receive arguments at call time. The factory pattern — a fixture that
yields a callable — enables `client = await authenticated_client("admin")` without requiring
a separate named fixture per role. `AsyncExitStack` tracks all `AsyncClient` contexts and
closes them at fixture teardown, regardless of how many times the factory was called.

**4. Keeping `async_client` (override-based) alongside new fixtures**

Replacing `async_client` in every test file would have touched `test_balance.py`,
`test_transactions_http.py`, `test_auth.py`, `test_users.py`, and `test_idempotency.py`.
Those tests validate business logic (balance calculation, transaction validation, etc.), not
the auth pipeline, so the override shortcut is appropriate there. The real-JWT fixtures are
used where the auth path itself is the subject under test (`test_rbac.py`).

---

## Step C Walkthrough Summary

| Step | What was implemented |
|------|----------------------|
| C-1 | `_seed_user(engine, email, password, role)` — direct DB INSERT |
| C-2 | `_make_db_override(engine)` — returns `override_get_db` callable |
| C-3 | `admin_token` fixture — seed + login + yield token str |
| C-4 | `auditor_token` fixture — same pattern, AUDITOR role |
| C-5 | `authenticated_client` factory — `AsyncExitStack` + baked `Authorization` header |
| C-6 | `auditor_client` replaced — token-based, same fixture name |
| C-7 | Two DONE-condition tests in `test_rbac.py` |
| C-8 | ruff / mypy / pytest all-green |

---

## Key Takeaways

### What did I learn?

I learned the factory fixture pattern in pytest: a fixture can yield a callable rather than a
value, letting callers pass arguments at test-call time. This solves the limitation that pytest
fixtures cannot receive runtime arguments directly. The `AsyncExitStack` from `contextlib` is
the right tool to manage multiple async context managers whose lifetimes are determined
dynamically inside a fixture.

I also learned the practical consequence of `clean_db` scoping: token fixtures must be
function-scoped because the `users` table is TRUNCATEd between tests. Session-scoped tokens
would reference rows that no longer exist, causing 401 errors on the second test.

### What would I do differently?

I would have added per-step commit commands to the Step C walkthrough from the start.
CLAUDE.md section 4.7 specifies this explicitly, but I omitted them in the initial walkthrough
and needed a correction mid-session. "One Step C block = one commit" is the rule.

### What surprised me?

The bootstrap problem with `POST /api/v1/users` requiring an admin to create an admin surprised
me slightly — in retrospect it's obvious, but it clarified why the direct-INSERT pattern is
the correct test setup approach for privileged seed data, not a workaround.

I was also initially unsure whether `clean_db` (autouse, depends on `engine`) would run
before or after the token fixture's user seeding. Tracing the pytest fixture dependency graph
confirmed the order: `engine` → `clean_db` pre-yield (TRUNCATE) → token fixture seeds user →
test body → token fixture teardown → `clean_db` post-yield (TRUNCATE again). The seeded user
is always present during the test body.

### What is worth remembering for future goals?

- **Factory fixture pattern**: fixture yields `Callable`, caller does `await factory("param")`.
  Use `AsyncExitStack` to manage the lifetime of objects created inside the factory.
- **Scoping rule for DB-backed fixtures**: if `clean_db` TRUNCATEs between tests, any fixture
  that depends on DB state must be function-scoped.
- **Privilege bootstrap**: seed privileged users directly via `async_sessionmaker`, not via the
  API, to avoid auth dependency loops in test setup.
- **`dependency_overrides` vs real JWT**: overrides are fine for business-logic tests; use real
  JWT fixtures in tests where the auth pipeline itself is the subject.
