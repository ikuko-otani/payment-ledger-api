# S3-4: OAuth2PasswordBearer + get_current_user 依存性

**Date**: 2026-05-21
**Branch**: `feature/s3-4-get-current-user-dependency`
**Sprint**: S3 — JWT Authentication + Role-Based Access Control

---

## Goal Overview

Implemented a shared `get_current_user` dependency that validates JWT tokens on every
protected endpoint. Key additions:

- `app/core/deps.py`: `oauth2_scheme` + `get_current_user` + `CurrentUser` type alias (new file)
- `app/api/v1/routes/accounts.py`: all three handlers protected with `_current_user: CurrentUser`
- `app/api/v1/routes/transactions.py`: both handlers protected with `_current_user: CurrentUser`
- `tests/test_auth_dependency.py`: 3 integration tests (no token → 401, valid JWT → 200, expired → 401)
- `tests/conftest.py`: `get_current_user` mock override added to `async_client`; new `unauthed_client`
  fixture added for auth-specific tests
- TD-002 (unauthenticated endpoints) closed

---

## Implementation Notes

### Files created / edited

| File | Change |
|------|--------|
| `app/core/deps.py` | NEW — `oauth2_scheme`, `get_current_user`, `CurrentUser` |
| `app/api/v1/routes/accounts.py` | EDIT — `CurrentUser` dependency added to all 3 handlers |
| `app/api/v1/routes/transactions.py` | EDIT — `CurrentUser` dependency added to both handlers |
| `tests/test_auth_dependency.py` | NEW — 3 integration tests for auth dependency |
| `tests/conftest.py` | EDIT — `get_current_user` mock override in `async_client`; new `unauthed_client` fixture |

---

## Key Concepts

### OAuth2PasswordBearer is a declaration, not a validator

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
```

`OAuth2PasswordBearer` does two things only:

1. Registers the OpenAPI security scheme (enables "Authorize" button in Swagger UI)
2. Extracts the `Bearer <token>` string from the `Authorization` header for each request

It performs **no JWT validation**. If the header is missing, it raises 401 automatically.
If the header is present, it passes the raw token string to the next dependency. Actual
signature and expiry verification happens inside `get_current_user`.

This separation of concerns is intentional: `oauth2_scheme` is about transport (where to
find the token), `get_current_user` is about trust (is this token valid?).

### get_current_user: the actual validation chain

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        sub: str | None = payload.get("sub")
        if sub is None:
            raise credentials_exception
        user_id = uuid.UUID(sub)
    except (JWTError, ValueError):
        raise credentials_exception
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user
```

`jwt.decode()` validates three things in one call:
- HMAC-SHA256 signature (tamper detection)
- `exp` claim (expiry)
- JSON structure (format)

All failures raise `JWTError` (which includes `ExpiredSignatureError` as a subclass).
`ValueError` is also caught because `uuid.UUID(sub)` raises it if `sub` is not a valid UUID
string — for example, if an attacker crafts a token with `"sub": "hello"`.

Every failure path raises the same `credentials_exception`. This prevents information leakage:
an attacker cannot distinguish between "bad signature", "expired", "sub missing", or
"user deleted" based on the response.

### sub claim: stored as str, parsed as UUID

S3-3 stored the user ID as `str(user.id)` in the `sub` claim. S3-4 reverses that:

```python
user_id = uuid.UUID(sub)  # convert back before passing to SQLAlchemy
```

SQLAlchemy's `Mapped[uuid.UUID]` column expects a Python `uuid.UUID` object in the `WHERE`
clause. Passing a plain string causes a type mismatch that results in 0 rows returned rather
than a visible error — a silent failure that is hard to diagnose.

### WWW-Authenticate: Bearer header (RFC 6750)

The `headers={"WWW-Authenticate": "Bearer"}` in `credentials_exception` is required by
RFC 6750 for protected resources. It tells the client which authentication scheme to use
for retry. Without this header, the response is technically a non-conformant 401.

This header is only needed on protected endpoints (the 401 from `get_current_user`).
The 401 from `POST /auth/login` itself does **not** need it — login is not a protected
resource, it is the authentication endpoint.

### CurrentUser type alias

```python
CurrentUser = Annotated[User, Depends(get_current_user)]
```

`Annotated[T, Depends(...)]` is FastAPI's idiomatic way to define reusable dependency
type aliases. In the route handler:

```python
async def list_accounts(db: DbDep, _current_user: CurrentUser) -> list[Account]:
```

FastAPI reads the `Depends(get_current_user)` from the annotation and resolves it before
calling the handler. The `_` prefix on `_current_user` signals "injected for its side
effect (authentication), not used in the handler body."

This is analogous to Laravel middleware — but per-parameter rather than per-route, giving
finer control over which handlers are protected.

### Dependency override strategy in tests

Adding `get_current_user` to endpoints broke all existing tests because they called
endpoints without a token. The fix used FastAPI's `dependency_overrides` dict:

```python
# conftest.py — async_client fixture
async def override_get_current_user() -> User:
    return User(id=uuid.uuid4(), email="fixture@example.com", ...)

fastapi_app.dependency_overrides[get_current_user] = override_get_current_user
```

For `test_auth_dependency.py`, which tests the auth mechanism itself, a separate
`unauthed_client` fixture was added that does **not** override `get_current_user`.
This keeps the fixture responsibilities clear:

| Fixture | get_current_user | Purpose |
|---------|-----------------|---------|
| `async_client` | mocked | Business logic tests (auth assumed) |
| `unauthed_client` | real | Auth flow tests (validates JWT behavior) |

---

## Key takeaways

**What did I learn?**

I learned the precise boundary between `OAuth2PasswordBearer` and `get_current_user`:
the former is purely about extracting a string from an HTTP header and generating OpenAPI
metadata, while the latter is where all trust decisions are made. Conflating the two is a
common misconception — the scheme object does not validate anything.

I learned that `JWTError` covers `ExpiredSignatureError` as a subclass, so there is no
need to catch expiry separately. One `except (JWTError, ValueError)` block handles all
token failure modes, and the unified error response is intentional security design, not
just convenience.

I learned the dependency override split pattern for tests: a mocked `async_client` for all
existing business-logic tests, and a separate `unauthed_client` that runs real JWT
validation for auth-specific tests. This avoids modifying every existing test while still
allowing thorough coverage of the auth code path.

**What would I do differently?**

When adding a new FastAPI dependency to existing endpoints, I would update `conftest.py`'s
`dependency_overrides` in the same commit as the endpoint change — before running the test
suite. The cascade of 10 test failures was entirely predictable: any endpoint that gains a
new `Depends(...)` will break tests that call it without satisfying that dependency.

**What surprised me?**

The typo `"Bearder"` instead of `"Bearer"` in the `Authorization` header caused
`test_valid_token_returns_200` to return 401. FastAPI's `OAuth2PasswordBearer` is strict:
if the scheme prefix does not match `"Bearer"` exactly (case-insensitive check), it
treats the header as absent and raises 401. The error message gave no indication of a
header format problem, so the root cause was not immediately obvious from the test output.

**What is worth remembering for future goals?**

- `OAuth2PasswordBearer` extracts and declares; `get_current_user` validates. They are
  different responsibilities in different files.
- `JWTError` is a superclass — catching it covers expiry, signature failure, and format
  errors in one `except` clause.
- `uuid.UUID(sub)` is required before passing to a `Mapped[uuid.UUID]` column. String
  comparison against a UUID column silently returns 0 rows.
- All auth failures return the same 401 body. Differentiating them leaks information.
- When protecting an endpoint with a new `Depends(...)`, update `dependency_overrides` in
  `conftest.py` in the same commit to prevent a test cascade failure.
- `"Bearer"` in the Authorization header must be spelled exactly. A typo produces a 401
  with no hint of the actual cause.
