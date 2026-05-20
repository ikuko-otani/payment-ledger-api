# S3-3: JWTトークン生成 + POST /auth/login

**Date**: 2026-05-20
**Branch**: `feature/s3-3-jwt-login-endpoint`
**Sprint**: S3 — JWT Authentication + Role-Based Access Control

---

## Goal Overview

Implemented the login endpoint and JWT access token issuance. Key additions:

- `python-jose[cryptography]` added as dependency
- `app/core/config.py`: `secret_key` made required (no default); `algorithm` and
  `access_token_expire_minutes` added
- `app/core/security.py`: `create_access_token()` added
- `app/schemas/auth.py`: `LoginRequest` / `TokenResponse` schemas (new file)
- `POST /api/v1/auth/login`: email + password → JWT; 401 on any failure
- `tests/test_auth.py`: 3 integration tests (200+JWT, wrong password 401, unknown email 401)
- `.github/workflows/ci.yml`: `SECRET_KEY` / `ALGORITHM` / `ACCESS_TOKEN_EXPIRE_MINUTES`
  added to CI env

---

## Implementation Notes

### Files created / edited

| File | Change |
|------|--------|
| `app/core/config.py` | EDIT — `secret_key` required; `algorithm` / `access_token_expire_minutes` added |
| `app/core/security.py` | EDIT — `create_access_token()` added; `python-jose` imported |
| `app/schemas/auth.py` | NEW — `LoginRequest` / `TokenResponse` |
| `app/api/v1/routes/auth.py` | NEW — `POST /auth/login` endpoint |
| `app/api/v1/router.py` | EDIT — `auth.router` included |
| `.env` / `.env.example` | EDIT — `ALGORITHM` / `ACCESS_TOKEN_EXPIRE_MINUTES` added |
| `tests/test_auth.py` | NEW — 3 integration tests |
| `app/services/transaction_service.py` | FIX — renamed second `result` to `tx_result` |
| `.github/workflows/ci.yml` | FIX — 3 new env vars added to test job |
| `pyproject.toml` / `uv.lock` | EDIT — `python-jose[cryptography]` added |

---

## Implementation Notes

### JWT structure and create_access_token

`jwt.encode()` from `python-jose` produces a three-part string: `header.payload.signature`.

```python
def create_access_token(data: dict[str, object]) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
```

- **header**: algorithm metadata (`{"alg": "HS256", "typ": "JWT"}`), base64url-encoded
- **payload**: claims (`sub`, `exp`, etc.), base64url-encoded — readable by anyone
- **signature**: HMAC-SHA256 of `header.payload` using `SECRET_KEY` — only the server can
  produce or verify this

The server needs no database lookup at verification time. It recomputes the HMAC and compares
it with the signature in the token. If they match, the token was issued by this server and
has not been tampered with. This is the practical meaning of JWT being "stateless."

`data.copy()` is required before mutating: without it, the `"exp"` key would be added to the
dict the caller passed in, causing a subtle side-effect bug.

### User enumeration prevention

The login handler treats two distinct failure cases identically:

```python
if user is None or not verify_password(payload.password, user.hashed_password):
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
    )
```

If the two cases returned different messages or status codes, an attacker could probe the
endpoint with a list of email addresses and use the response difference to determine which
addresses are registered. Returning the same 401 with the same message for both cases prevents
this reconnaissance technique, known as **user enumeration**.

This pattern is a standard security requirement and an ARCHITECTURE.md candidate.

### secret_key without a default

Removing the `= "dev-secret"` default forces the field to be required by pydantic-settings:

```python
secret_key: str  # no default — required from .env
```

This ensures the process fails at startup if `SECRET_KEY` is absent from the environment,
rather than silently issuing tokens signed with a predictable key. The failure is immediate
and obvious, preventing the "running fine in dev with the wrong config" class of bugs.

### CI env vars impact of removing a default

Removing a default from `config.py` breaks CI unless the new required fields are also added
to the test job's `env:` block in the workflow. The process exits with `ValidationError` before
any test setup can run, producing an `ImportError` in conftest rather than a test failure.

The values used in CI (`ci-test-secret`, `HS256`, `30`) do not need to be production-safe —
they exist only so `Settings()` can instantiate during the testcontainer run.

### mypy: variable name reuse with SQLAlchemy generics

`create_transaction()` used `result` for two consecutive `db.execute()` calls with different
`select()` targets — one for `Account`, one for `Transaction`. mypy inferred the return type
of the second `result.scalar_one()` as `Account` based on the earlier assignment, producing
a false `[return-value]` error.

The fix was to rename the second assignment:

```python
# Before (ambiguous to mypy):
result = await db.execute(select(Account)...)   # type: Result[tuple[Account]]
...
result = await db.execute(select(Transaction)...)
return result.scalar_one()  # mypy: "got Account, expected Transaction"

# After (explicit):
tx_result = await db.execute(select(Transaction)...)
return tx_result.scalar_one()  # mypy: OK
```

This is a SQLAlchemy 2.0 + mypy type inference limitation, not a runtime bug. The production
behavior was correct; only the type checker was confused.

---

## Key takeaways

**What did I learn?**

I learned the concrete mechanics of JWT issuance: copying the claims dict, computing an `exp`
timestamp as a `datetime`, and calling `jwt.encode()`. I now understand that the `payload`
section of a JWT is just base64url-encoded JSON — readable by anyone — and that the security
guarantee comes entirely from the `signature` section, which only the holder of `SECRET_KEY`
can produce or verify. This makes the "stateless" claim concrete: there is nothing to look up;
verification is a pure computation.

I learned the user enumeration prevention pattern: treating "unknown email" and "wrong password"
as a single indistinguishable failure case at the HTTP boundary. The unified `or` condition in
the handler makes this structural rather than relying on a developer to remember to write two
separate identical error responses.

I learned that removing a default value from a `pydantic_settings` field has a blast radius
beyond the application code itself — it also breaks CI if the workflow does not supply the
newly required environment variable.

**What would I do differently?**

When removing a default from `config.py`, I would immediately check `.github/workflows/ci.yml`
for the affected field and add it to the `env:` block in the same commit, before pushing.
The CI failure was predictable from first principles.

I would use distinct variable names for sequential `db.execute()` calls in the same function
(`account_result`, `tx_result`) from the start, rather than reusing `result`. The mypy error
was easy to fix, but the habit of naming intermediates distinctly makes the intent clearer
and avoids the type inference ambiguity entirely.

**What surprised me?**

The mypy error in `transaction_service.py` surfaced during S3-3 even though neither
`transaction_service.py` nor the specific `result` variable were changed in this goal.
The error was pre-existing but had gone undetected because mypy had not been run on the full
`app/` directory until now. Running `mypy app/` for the first time caught a latent bug across
the whole codebase, not just the files touched in this sprint.

I was also surprised that the CI `ImportError` appeared in `conftest.py` rather than pointing
directly at `config.py`. When `Settings()` raises `ValidationError` during module import,
Python wraps it in an `ImportError` at the import site, which is several layers away from the
root cause. Reading the full traceback from the bottom was the key to diagnosing it quickly.

**What is worth remembering for future goals?**

- JWT `payload` is public; `signature` is the secret. Never put sensitive data in the payload.
- `data.copy()` before mutating in `create_access_token` — prevents side-effect bugs on the
  caller's dict.
- User enumeration prevention: one `if user is None or not verify_password(...)` covers both
  cases and is intentional security design, not code golf.
- Removing a `pydantic_settings` field default → immediately update CI `env:` in the same commit.
- Reuse of a variable name across two `select()` calls with different ORM models confuses mypy's
  generic type inference. Use distinct names (`account_result`, `tx_result`, etc.).
- `mypy app/` should be run as part of every goal, not just on the files changed in that goal —
  it can surface latent bugs in untouched files.
