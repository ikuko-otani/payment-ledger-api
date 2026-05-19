# S3-2: パスワードハッシュ化 + UserCreate エンドポイント

**Date**: 2026-05-19
**Branch**: `feature/s3-2-password-hash-user-create`
**Sprint**: S3 — JWT Authentication + Role-Based Access Control

---

## Goal Overview

Built the user registration endpoint on top of the `User` model from S3-1. Key additions:

- `bcrypt` direct usage for password hashing (replaced unmaintained `passlib`)
- `app/core/security.py`: `get_password_hash()` / `verify_password()`
- `app/services/user_service.py`: `create_user()` with duplicate-email 409 guard
- `POST /api/v1/users` endpoint returning 201 on success
- `users` added to `clean_db` TRUNCATE in `conftest.py`
- Integration tests: success 201, duplicate 409, hashed password in DB

---

## Implementation Notes

### Files created / edited

| File | Change |
|------|--------|
| `app/core/security.py` | NEW (overwritten stub) — `get_password_hash` / `verify_password` |
| `app/services/user_service.py` | NEW — `create_user` service |
| `app/api/v1/routes/users.py` | NEW — `POST /users` endpoint |
| `app/api/v1/router.py` | EDIT — added `users.router` |
| `tests/conftest.py` | EDIT — added `users` to TRUNCATE |
| `tests/test_users.py` | NEW — 3 integration tests |
| `pyproject.toml` | EDIT — `bcrypt` added (passlib removed) |
| `app/core/config.py` | EDIT — `# type: ignore[call-arg]` on `Settings()` |

### passlib → bcrypt direct: why the switch

`passlib` 1.7.4 (last released 2020) reads `bcrypt.__about__.__version__` to detect the
bcrypt version. The `__about__` module was removed in `bcrypt` 4.0.0, causing an
`AttributeError` at runtime. Rather than downgrading bcrypt, we removed passlib entirely
and called the bcrypt API directly:

```python
import bcrypt

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )
```

The only behavioral difference from the passlib wrapper: `str` ↔ `bytes` conversion must be
explicit. This is more transparent than the passlib abstraction.

### db.flush() vs db.commit() in create_user

```python
db.add(user)
await db.flush()    # sends INSERT SQL; transaction still open
await db.refresh(user)  # re-reads the row (picks up server defaults like created_at)
return user
```

`flush()` sends the SQL without closing the transaction. The calling layer (FastAPI's
`override_get_db`) owns the `commit()`. This keeps services transaction-neutral and
composable — a service can be called multiple times inside a single transaction without
accidentally committing early.

PHP/PDO analogy: `flush()` ≈ executing a prepared statement before calling `$pdo->commit()`.

### Duplicate email: 409 from service layer

`user_service.create_user()` raises `HTTPException(status_code=409)` directly when the email
already exists. FastAPI propagates this through to the HTTP response without needing a
`try/except` in the route handler. The route stays to one line:

```python
return await user_service.create_user(db, payload)
```

### Return type in route handler: User, not UserResponse

```python
async def register_user(...) -> User:
    return await user_service.create_user(db, payload)
```

The function physically returns a `User` ORM object. FastAPI uses `response_model=UserResponse`
to serialize it via Pydantic's `from_attributes=True`. Annotating the return type as
`UserResponse` satisfies no real need and causes a mypy error because the types don't match.

### config.py mypy suppression

`Settings()` is called with no arguments, but `database_url: str` has no default.
`pydantic_settings` reads it from the environment at runtime, which mypy cannot see.
Suppressed with `# type: ignore[call-arg]` on the instantiation line.
Tracked as tech debt to be addressed properly (add a default or use `model_validator`).

### S3-1 enum casing concern — resolved

S3-1 noted that the migration generated `sa.Enum('ADMIN', 'AUDITOR', ...)` with uppercase
names, while Python enum values are lowercase (`"admin"`, `"auditor"`). The test
`assert body["role"] == "auditor"` passed, confirming SQLAlchemy stores and retrieves the
lowercase value string, not the uppercase member name.

---

## Key takeaways

**What did I learn?**

I learned that `passlib` is effectively unmaintained and breaks with current `bcrypt` versions.
When a library wraps another library but hasn't been updated in years, version incompatibilities
surface as cryptic `AttributeError`s rather than obvious deprecation warnings. Switching to the
underlying library directly removed a layer of indirection and made the encode/decode
responsibilities explicit.

I learned that in SQLAlchemy async, `flush()` and `commit()` have distinct roles and that
services should call `flush()` + `refresh()` but leave `commit()` to the caller. This makes
services composable inside larger transactions — a pattern analogous to avoiding auto-commit in
PDO and managing transactions explicitly at the application boundary.

I learned the difference between a route handler's physical return type and FastAPI's
`response_model` serialization. The function returns `User`; `response_model=UserResponse`
tells FastAPI how to serialize it for the HTTP response. These are two separate concerns, and
mypy tracks the physical return type, not the response model.

**What would I do differently?**

I would investigate `passlib` compatibility before adding it, rather than after hitting the
runtime error. A quick check of the PyPI release date ("last release 2020") and the bcrypt
changelog would have flagged the risk upfront and saved the debugging round-trip.

I would also add `app.core.config` to the mypy overrides from the start when introducing
`pydantic_settings` with required fields, rather than discovering it mid-goal. The `Settings()`
pattern with environment-sourced fields is a known mypy blind spot.

**What surprised me?**

The `db.refresh()` call silently accepts zero arguments without raising a `TypeError` at
definition time — the error only surfaced when mypy ran. In Python, `async def refresh(self,
instance, ...)` with a required positional argument does not fail at parse time if the call
site is written as `await db.refresh()`. This is a case where mypy catches a real mistake
that tests might also miss if the fixture setup hides the SQLAlchemy-level error.

**What is worth remembering for future goals?**

- `passlib` is unmaintained; prefer `bcrypt` directly or a maintained alternative (`pwdlib`).
- Service layer: `flush()` + `refresh()`, not `commit()`. Commit belongs to the transport layer.
- Route handler return type annotation should match the physical return value (`User`), not the
  Pydantic response model (`UserResponse`). FastAPI handles serialization separately.
- `scalar_one_or_none()` is safer than `first()` for uniqueness checks: it raises if more than
  one row is returned, surfacing data integrity problems rather than silently masking them.
- `pydantic_settings` `BaseSettings()` with required fields always needs `# type: ignore[call-arg]`
  or a workaround — add it immediately when the class is instantiated.
- The S3-1 enum casing concern (uppercase names vs lowercase values) was a non-issue:
  SQLAlchemy correctly maps `UserRole.AUDITOR` → `"auditor"` in the DB. No workaround needed.
