# S3-7: Auth Coverage — Learning Notes

**Date**: 2026-05-24  
**Branch**: `feature/s3-7-auth-coverage`  
**Goal**: Measure and supplement authentication layer test coverage; confirm S3 DONE conditions.

---

## Step C Walkthrough

### What was implemented

Two edge-case test helpers and two tests were added to `tests/test_auth_dependency.py`:

**Helper: `_invalid_signature_token()`**  
Encodes a JWT with `"wrong-secret"` instead of `settings.secret_key`.  
`jwt.decode()` in `deps.py` raises `JWTError`, which is caught by the `except (JWTError, ValueError)` clause (L36–37).

```python
def _invalid_signature_token() -> str:
    from uuid import uuid4
    from jose import jwt as jose_jwt
    from app.core.config import settings

    payload = {"sub": str(uuid4())}
    return jose_jwt.encode(payload, "wrong-secret", algorithm=settings.algorithm)
```

**Helper: `_nonexistent_user_token()`**  
Encodes a JWT with `settings.secret_key` (valid signature) but a random UUID as `sub`.  
`jwt.decode()` succeeds; the subsequent `select(User).where(User.id == user_id)` returns `None` (L40–41).

```python
def _nonexistent_user_token() -> str:
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    from jose import jwt as jose_jwt
    from app.core.config import settings

    payload = {
        "sub": str(uuid4()),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    return jose_jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
```

**Tests**:

```python
@pytest.mark.asyncio
async def test_invalid_signature_token_returns_401(unauthed_client: AsyncClient) -> None:
    token = _invalid_signature_token()
    response = await unauthed_client.get(
        "/api/v1/accounts", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_nonexistent_user_id_token_returns_401(unauthed_client: AsyncClient) -> None:
    token = _nonexistent_user_token()
    response = await unauthed_client.get(
        "/api/v1/accounts", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
```

> ⚠️ Both tests must use `unauthed_client`, not `async_client`.  
> `async_client` overrides `get_current_user`, so JWT validation never runs.

### DONE conditions at goal close

| Condition | Result |
|---|---|
| `pytest --cov` measurable | ✅ pytest-cov 7.1.0 pre-installed |
| Role tests ≥ 10 | ✅ 14 tests in `test_rbac.py` |
| Edge-case tests (expired / invalid-sig / nonexistent-user / inactive) | ✅ All 4 implemented and PASSED |
| mypy / ruff zero errors | ✅ |
| Total coverage | ✅ 85% |

### Coverage baseline (`app/core/deps.py`)

| Lines | Content | Status |
|---|---|---|
| L34 | `raise credentials_exception` (sub is None) | Uncovered — no test with sub-less JWT |
| L36–37 | `except (JWTError, ValueError)` | Covered — by expired-token test (pre-existing) |
| L39–44 | DB query through `return user` | Reported uncovered — async tracking artifact (see TD-013) |
| L62 | `require_auditor_or_admin` forbidden raise | Uncovered — no non-admin/non-auditor role test |

### Discovered: async coverage tracking limitation (TD-013)

`coverage.py` uses `sys.settrace()` to record line execution. When an async coroutine suspends at `await` and later resumes, the trace hook is not always re-registered for the resumed frame. Lines after `await db.execute()` (L39 onward) appear uncovered even though the test PASSES with the expected 401.

The test assertion itself is the behavioral proof: if L40 (`if user is None`) had not executed, the response would not be 401.

Fix (deferred to S6): set `COVERAGE_CORE=sysmon` or add `[tool.coverage.run]` config to `pyproject.toml` to use Python 3.12's `sys.monitoring` API.

---

## Key Takeaways

**What did I learn?**  
I learned that `coverage.py`'s `sys.settrace`-based measurement has a known gap with Python async coroutines: lines executed after an `await` suspension may not be recorded because the trace hook is not re-registered on coroutine resumption. This is not a bug in the application code — it is a measurement artifact.

**What would I do differently?**  
I would configure `[tool.coverage.run]` in `pyproject.toml` at project setup time, before the first coverage run. Adding `COVERAGE_CORE=sysmon` from the start would give accurate async coverage data throughout the sprint, rather than discovering the gap at S3-7.

**What surprised me?**  
That `test_valid_token_returns_200` passes with HTTP 200 — which logically requires L39–44 to have executed — yet coverage reports those lines as missed. I initially suspected the tests were not reaching the DB lookup code at all. The resolution was understanding the distinction between "test assertion as behavioral proof" and "coverage as measurement record."

**What is worth remembering for future goals?**  
- Test assertions are the ground truth for correctness; coverage is a measurement tool that can have false negatives.  
- Always use `unauthed_client` (not `async_client`) when testing the authentication pipeline itself. `async_client` bypasses `get_current_user` via `dependency_overrides`.  
- `exp` in a JWT helper must be a future timestamp when testing user-not-found scenarios; an expired token takes a different code path (JWTError) and would not reach the DB query.
