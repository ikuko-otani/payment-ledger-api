# S6-6: Security Tests (Auth Bypass + SQL Injection)

**Date**: 2026-06-11
**Goal**: S6-6 — Add security tests (auth bypass + SQL injection)
**Branch**: feature/s6-6-security-tests
**PR**: #59

## Goal Overview

Added `tests/test_security.py`, an explicit pytest-based security test suite proving:

- protected endpoints reject unauthenticated requests (401),
- a tampered/malformed JWT is rejected (401),
- SQL-injection-style payloads are safely handled regardless of whether they hit a
  narrowly-typed (`uuid.UUID`) or broadly-typed (`str`) parameter.

Existing coverage was deliberately **not duplicated**: expired-JWT → 401
(`tests/test_auth_dependency.py::test_expired_token_returns_401`) and
auditor → 403 on admin endpoints (`tests/test_rbac.py`) were left as-is and are
cross-referenced from the new file's module docstring.

## Implementation

### 1. Unauthenticated access -> 401 (4 endpoints)

The Notion "やること" listed four specific protected endpoints that had no existing
unauthenticated-access test (only `GET /accounts` was covered elsewhere):

```python
_PROTECTED_ENDPOINTS: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/transactions", {"json": {}}),
    (
        "GET",
        "/api/v1/accounts/00000000-0000-0000-0000-000000000000/balance",
        {"params": {"as_of": "2024-01-01T00:00:00"}},
    ),
    ("GET", "/api/v1/ledger", {}),
    ("POST", "/api/v1/accounts", {"json": {}}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "kwargs"), _PROTECTED_ENDPOINTS)
async def test_unauthenticated_request_to_protected_endpoint_returns_401(
    unauthed_client: AsyncClient, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    response = await unauthed_client.request(method, path, **kwargs)
    assert response.status_code == 401
```

⚠️ For `POST` endpoints, an empty `{"json": {}}` body is enough — `get_current_user`
(auth) runs before body validation, so a missing/invalid body never masks the 401
(same pattern as `test_auditor_cannot_post_transaction` in `test_rbac.py`, which gets
403 with `{}`). For `GET /accounts/{id}/balance`, the required `as_of` query param
must be supplied, otherwise a 422 (missing param) would mask the 401.

### 2. Tampered JWT ("xxx.yyy.zzz") -> 401

```python
@pytest.mark.asyncio
async def test_tampered_jwt_returns_401(unauthed_client: AsyncClient) -> None:
    response = await unauthed_client.get(
        "/api/v1/accounts", headers={"Authorization": "Bearer xxx.yyy.zzz"}
    )
    assert response.status_code == 401
```

💡 **JWT signature verification (HS256/HMAC)**: `app/core/deps.py::get_current_user`
calls `jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])`.
HS256 is HMAC-SHA256 — a symmetric scheme. The signature is
`HMAC-SHA256(base64url(header) + "." + base64url(payload), secret_key)`. On decode,
the server recomputes this HMAC over the received header+payload and compares it to
the provided signature. Any tampering with the payload (e.g. changing `sub` or
escalating role) invalidates the signature because the attacker doesn't know
`secret_key`. Both signature mismatches and structurally malformed tokens (like
`xxx.yyy.zzz`, which fails base64/JSON decoding before signature verification is even
reached) raise `JWTError`, caught by the same `except (JWTError, ValueError)` clause
→ 401. Expiry (`exp` claim) is checked in the same call and raises
`ExpiredSignatureError` (a `JWTError` subclass) → also 401.

⚠️ **DONE-condition wording vs. actual behavior**: Notion's DONE condition said
"tampered JWT → 403", but `deps.py` always returns 401 for `JWTError` — 403 is
reserved for role checks (`require_admin` / `require_auditor_or_admin`), which only
run *after* authentication succeeds. Per "やらないこと" (no auth implementation
changes), this test asserts the actual behavior (401), matching the existing
`test_invalid_signature_token_returns_401`. The Notion wording should be corrected to
401 in the 設計メモ.

### 3. SQL injection via `account_id` path param -> 422

```python
@pytest.mark.asyncio
async def test_sql_injection_in_account_id_path_param_returns_422(
    async_client: AsyncClient,
) -> None:
    payload = "'; DROP TABLE accounts; --"
    response = await async_client.get(
        f"/api/v1/accounts/{payload}/balance",
        params={"as_of": "2024-01-01T00:00:00"},
    )
    assert response.status_code == 422
```

This returns 422 purely because `id: uuid.UUID` fails Pydantic's UUID coercion — the
payload never reaches the service/ORM layer.

### 4. (Bonus) SQL injection via `currency_code` query param -> 200 + `[]`

```python
@pytest.mark.asyncio
async def test_sql_injection_in_currency_code_query_param_returns_empty_list(
    async_client: AsyncClient,
) -> None:
    response = await async_client.get(
        "/api/v1/ledger",
        params={"currency_code": "'; DROP TABLE accounts; --"},
    )
    assert response.status_code == 200
    assert response.json() == []
```

`currency_code: str | None` passes type validation (it's a valid string), so this
exercises the *other* defense layer — see Knowledge Check Q2 below and
[`docs/learning-notes/concepts/sql-injection-defense-layers.md`](concepts/sql-injection-defense-layers.md)
for the full write-up.

## Knowledge Check (from Notion)

**Q1: Where is JWT signature verification performed? Explain the tamper-detection mechanism.**

In `app/core/deps.py::get_current_user`, via `jwt.decode(token, settings.secret_key,
algorithms=["HS256"])`. HS256 is HMAC-SHA256 (a symmetric scheme); the signature is
`HMAC-SHA256(base64url(header) + "." + base64url(payload), secret_key)`. On
verification, the server recomputes this HMAC over the received header+payload and
compares it to the token's signature. An attacker who doesn't know `secret_key`
cannot regenerate a valid signature after tampering with the payload, so the mismatch
raises `JWTError` → 401. Expiry (`exp`) is checked in the same `jwt.decode()` call and
raises `ExpiredSignatureError` (a `JWTError` subclass), which also results in 401.
Relation to TD-023 (ecdsa/Dependabot alert): this app uses only HS256 (HMAC), so the
vulnerable ECDSA asymmetric-key code path in `ecdsa` is never exercised.

**Q2: Are there cases where SQL injection can still occur even when using the SQLAlchemy ORM?**

The ORM itself (`select(...).where(Model.col == value)`) generates parameterized
queries (SQLAlchemy → asyncpg → Postgres bind parameters) and is safe. However, raw
SQL built via string concatenation — e.g. `db.execute(text(f"... {user_input}
..."))` — would still be vulnerable to SQL injection even though the ORM is in use.
All `text()` usages in this repository (e.g. `server_default=text("true")`) are
static and contain no user input. See
[sql-injection-defense-layers.md](concepts/sql-injection-defense-layers.md) for
details.

**Q3: Name three items from the OWASP Top 10 (2021) that this API should address.**

- **A01: Broken Access Control** — Role-based access control via `require_admin` /
  `require_auditor_or_admin`. Covered by `test_rbac.py` and this goal's
  unauthenticated-401 tests.
- **A02: Cryptographic Failures** — JWT signing (HS256/HMAC) and password hashing
  (bcrypt). TD-023 (ecdsa) also falls into this category.
- **A03: Injection** — This goal's SQLi test suite (dual defense: type-validation
  layer + parameterized-query layer).

## Key Takeaways

- I learned the precise mechanism behind JWT tamper detection: HS256 is HMAC-SHA256
  (symmetric), and the server re-derives the signature from the received
  header+payload and compares it — there's no "decryption" step, just a
  recomputation-and-compare. This made the PHP-session-vs-JWT distinction click for
  me: sessions don't need this because the data never leaves the server.
- I learned that "ORM = safe from SQLi" is too coarse a statement. There are two
  independent layers — type validation (only blocks narrow types like UUID) and
  parameterized queries (blocks everything, because the SQL text is parsed by
  Postgres *before* the parameter value is even sent). The `account_id` test only
  proves the first layer; the `currency_code` test proves the second.
- I was surprised that the deepest part of this goal wasn't writing the test code
  (which was short and reused existing fixtures) but understanding *why* a bind
  parameter can't be reinterpreted as SQL — the "parse happens before substitution"
  framing, and Postgres' Parse/Bind/Execute protocol stages, was the key piece.
- I also ran into a Notion DONE-condition wording that didn't match the actual
  implementation (403 vs. 401 for a tampered JWT). The right move was to test actual
  behavior and document the discrepancy, not to change `deps.py` to match the wording
  — worth remembering when DONE conditions and "やること" disagree in future goals.
- For future goals: if a `text(f"...")` raw-SQL pattern is ever introduced anywhere in
  `app/`, the `currency_code`-style test (string param + SQLi payload → expect a safe
  no-match result, not a 500/syntax error) is the template for a regression test on
  that new code path.
- Unrelated to the test code itself: this PR's first CI run failed on the `lint` job's
  `pip-audit` step with a transient PyPI 503 (`Backend is unhealthy`). Re-running the
  failed job was enough — useful to know this kind of CI noise exists and is not the
  same as the OSV/pip-audit version-matching issue documented in TD-023.

## References

- `app/core/deps.py` — `get_current_user`, `require_admin`, `require_auditor_or_admin`
- `app/core/security.py` — `create_access_token` (HS256 signing)
- `tests/test_auth_dependency.py` — expired JWT, invalid-signature JWT tests (not duplicated)
- `tests/test_rbac.py` — auditor → 403 tests (not duplicated)
- [sql-injection-defense-layers.md](concepts/sql-injection-defense-layers.md)
- TD-023 (`docs/tech-debt.md`) — ecdsa/Dependabot alert, HS256 background
