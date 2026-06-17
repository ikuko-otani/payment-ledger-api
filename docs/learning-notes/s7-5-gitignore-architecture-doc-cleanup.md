# S7-5: .gitignore cleanup + ARCHITECTURE.md fixes + JWT claims optimization

**Date**: 2026-06-17
**Branch**: `feature/s7-5-gitignore-architecture-doc-cleanup`
**PR**: #78
**Scope**: TD-010 (.gitignore), TD-007 (ARCHITECTURE.md / docs/adr alignment), TD-015 (get_current_user DB query removal)

---

## Step C Walkthrough

### C-1: TD-010 — .gitignore cleanup

Added the following patterns that were missing:

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.idea/
.vscode/
dist/
build/
*.egg-info/
```

**Key point**: `*.py[cod]` is bracket notation matching `*.pyc`, `*.pyo`, and `*.pyd` — three patterns in one line. Follows the GitHub Python .gitignore template convention.

### C-2: TD-007 — ARCHITECTURE.md restructure

Two problems fixed:

1. **Label conflict**: `ARCHITECTURE.md` used `ADR-NNN` labels for inline design decisions, creating a false impression that they were the same as `docs/adr/` files. Renamed all 9 inline `### ADR-NNN —` headings to `### Design Decision:`. Added a note clarifying that the two numbering systems are independent.

2. **Stale content** (4 items):
   - ADR-003 section: updated from PostgreSQL UNIQUE to Redis (changed in S2-3)
   - Section 6 "What I Would Add in Production": removed Redis (already in use)
   - Section 4 Tech Stack: `python-jose` → `PyJWT` (migrated in S7-3)
   - Section 9.3: `app/core/cache.py` → `app/core/redis.py` (deleted in S7-4)

### C-3: TD-015 (1/5) — auth.py: embed role/is_active in JWT

Changed `create_access_token` call at login to include role and is_active:

```python
token = create_access_token({
    "sub": str(user.id),
    "role": user.role.value,   # UserRole enum → string
    "is_active": user.is_active,
})
```

### C-4: TD-015 (2/5) — deps.py: remove DB dependency

Rewrote `get_current_user` to build `TokenUser` from JWT claims only:

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),  # db: AsyncSession removed
) -> TokenUser:
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    sub = payload.get("sub")
    role_str = payload.get("role")
    is_active = payload.get("is_active")
    if sub is None or role_str is None or is_active is None:
        raise credentials_exception   # missing claims → 401
    if not is_active:
        raise credentials_exception   # is_active=False claim → 401
    return TokenUser(id=uuid.UUID(sub), role=UserRole(role_str), is_active=is_active)
```

Validation logic: if any of `sub`, `role`, `is_active` are absent from the JWT payload, raise 401.
Old JWTs (without role/is_active claims) are automatically rejected.

### C-5: TD-015 (3/5) — service layer type update

`account_service.py` and `currency_service.py` changed `current_user: User` → `current_user: TokenUser`. No logic changes — only `.id` was used in both files, which `TokenUser` also provides.

### C-6: TD-015 (4/5) — conftest.py override update

`override_get_current_user` changed to return `TokenUser` to match the new production return type:

```python
async def override_get_current_user() -> TokenUser:
    return TokenUser(
        id=_FIXTURE_ADMIN_ID,
        role=UserRole.ADMIN,
        is_active=True,
    )
```

Also removed 8 stale `# type: ignore[...]` comments that mypy `--strict` flagged as `unused-ignore` (library type stubs had improved; the suppressed errors no longer existed).

### C-7: TD-015 (5/5) — test updates

**test_auth_dependency.py**: `_nonexistent_user_token` now returns 401 because the JWT lacks `role`/`is_active` claims (not because the UUID is absent from the DB). Comment updated to reflect the new reason.

**test_rbac.py**: `test_inactive_user_returns_401` replaced with `test_inactive_user_jwt_claim_returns_401`. The new test forges a JWT with `is_active=False` directly — because deactivating in the DB no longer affects existing tokens (the security trade-off documented in ADR-006).

### Latency measurement (TD-015)

| Metric | Value |
|--------|-------|
| Before (S7-4, cache hit) | ~65ms avg |
| After (S7-5, GET /accounts, requests 2–5) | ~37ms avg |
| Improvement | ~43% |
| Remaining latency cause | accounts DB query (get_current_user no longer contributes) |

Note: measurement endpoint changed from `GET /accounts/{id}/balance` to `GET /accounts`. Both reflect the removal of the `get_current_user` DB round-trip.

---

## Key Takeaways

### What did I learn?

- **`*.py[cod]` glob notation** matches three extensions in one pattern (`*.pyc`, `*.pyo`, `*.pyd`). Writing all three separately is valid but verbose; the bracket form follows the GitHub Python template and is considered idiomatic.

- **`# type: ignore` comments go stale** when library type stubs improve over time. mypy `--strict` enables `--warn-unused-ignores`, which flags these. The fix is simply to remove the now-unnecessary comments — no logic change needed.

- **JWT claims embedding is the standard pattern** for eliminating per-request user DB lookups. The trade-off is that role changes and deactivations are not reflected in existing tokens until expiry. The acceptable window is the token's lifetime (`ACCESS_TOKEN_EXPIRE_MINUTES`).

- **FastAPI `Depends` return type propagates through type aliases**: changing `get_current_user` to return `TokenUser` automatically updated `AdminUser`, `CurrentUser`, and `AuditorOrAdminUser` — no changes needed in the route files that use those aliases.

- **When `override_get_current_user` in conftest.py must match the production return type**: if production returns `TokenUser` but the test override returns `User`, mypy catches the mismatch. Always update the override when the production function's return type changes.

- **Two ADR numbering systems evolved organically**, not by design. `ARCHITECTURE.md` started calling its inline design sections "ADR-NNN" independently of the `docs/adr/` files. The fix was to rename the inline labels to "Design Decision:" to differentiate them from formal ADR files.

### What would I do differently?

- **Use the same endpoint for before/after latency comparison**. The TD-015 baseline was measured on `GET /accounts/{id}/balance` (cache hit), but the S7-5 measurement used `GET /accounts`. The direction of improvement is the same, but a true apples-to-apples comparison would use the same endpoint and parameters.

- **Avoid `ADR-NNN` labels in inline documentation from the start**. Had the ARCHITECTURE.md sections been named "Design Decision:" originally, the TD-007 confusion would never have arisen. When inline rationale and standalone ADR files coexist, differentiate their labels explicitly.

- **Periodically audit `# type: ignore` comments** as part of mypy maintenance, especially after dependency upgrades. Stale suppression comments accumulate silently until `--warn-unused-ignores` is enabled.

### What surprised me?

- **The grep false positive from `test_balance_cache.py`**: the pattern `cache\.py` matched the filename `test_balance_cache.py` because the string "cache.py" appears at the end. A more precise pattern (`core/cache\.py`) would have avoided the confusion.

- **The stale `# type: ignore` errors in conftest.py were pre-existing** and not caused by the Step C-6 changes. mypy `--strict`'s `--warn-unused-ignores` exposed them because we hadn't run full strict checks on the test files before.

- **`test_inactive_user_returns_401` needed a name change**, not just a content change. The test name was asserting a specific mechanism ("inactive user → 401") that no longer holds in the same way. Renaming to `test_inactive_user_jwt_claim_returns_401` makes the test document the new mechanism accurately.

### What is worth remembering for future goals?

- **JWT claims design is an interview topic**: "why did you embed role in the JWT instead of fetching from DB?" → "to eliminate per-request DB lookups; the trade-off is a revocation delay bounded by token expiry." See `docs/adr/006-jwt-claims-no-db-per-request.md`.

- **`*.py[cod]` covers pyc + pyo + pyd** — don't add them as separate lines alongside it.

- **`docker compose up -d`** creates containers if missing AND starts them. `docker compose start` only starts existing containers. Always use `up -d` as the default.

- **Changing a FastAPI dependency's return type has a cascade**: the dependency function, type aliases, service-layer parameter types, and test overrides all need to stay in sync. mypy catches most of these, but conftest overrides are easy to miss if not running mypy over the test directory.
