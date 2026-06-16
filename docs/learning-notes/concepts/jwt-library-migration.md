# JWT library migration: python-jose → PyJWT

> Date: 2026-06-16 | Context: TD-023 (PR #76)
> Purpose: Why we replaced `python-jose` with `PyJWT`, what changed in the
> code, and what to watch out for when migrating any third-party library.

---

## 1. Why we migrated

`python-jose` pulled in `ecdsa` as a transitive dependency.
GitHub Dependabot flagged `ecdsa==0.19.2` for GHSA-wj6h-64fc-37mp
(CVE-2024-23342, "Minerva timing attack on P-256 ECDSA", HIGH severity).

Two facts made this safe to ignore in practice, but not safe to leave unresolved:

- The app uses **HS256 (HMAC-SHA256, symmetric key)** for JWTs. The vulnerable
  code paths in `ecdsa` (ECDSA signing/ECDH) are never executed.
- The `ecdsa` maintainer has stated there is no planned fix; side-channel
  attacks are out of scope for a pure-Python library.

The options were:
1. Dismiss the Dependabot alert ("vulnerable code not used") — resolves the
   alert but leaves an unmaintained library in the dependency tree.
2. Migrate to `PyJWT` — permanently removes `ecdsa`, and moves to a library
   that is actively maintained (regular releases; `python-jose` last released
   October 2022).

We chose **option 2** for long-term health.

---

## 2. API comparison: what actually changed

For HS256, the encode/decode surface is nearly identical.
Only three things differ:

| | python-jose | PyJWT |
|---|---|---|
| Import | `from jose import jwt` | `import jwt` |
| `encode()` return type | `str` but typed as `str \| bytes` (stubs inconsistent) | `str` (correctly typed) |
| Exception class | `JWTError` (imported separately) | `jwt.PyJWTError` (on the module) |

### Before (python-jose)

```python
# security.py
from typing import cast
from jose import jwt

return cast(str, jwt.encode(to_encode, key, algorithm=algorithm))

# deps.py
from jose import JWTError, jwt

except (JWTError, ValueError) as e:
```

### After (PyJWT)

```python
# security.py
import jwt

return jwt.encode(to_encode, key, algorithm=algorithm)  # cast() no longer needed

# deps.py
import jwt

except (jwt.PyJWTError, ValueError) as e:
```

The `cast(str, ...)` wrapper was a workaround for `python-jose`'s imprecise
type stubs. `PyJWT` returns `str` directly with correct type annotations, so
`cast` can be removed.

---

## 3. Key pitfall: test files also import the old library

The migration broke 4 tests in `tests/test_auth_dependency.py` with:

```
ModuleNotFoundError: No module named 'jose'
```

These helper functions were crafting specific JWT tokens (expired, wrong
signature, missing `sub` claim) for edge-case tests — and each function
contained a **lazy import** of `jose` inside the function body:

```python
def _expired_token() -> str:
    from jose import jwt as jose_jwt          # ← still importing old library
    from app.core.config import settings
    payload = {"sub": "...", "exp": datetime.now(UTC) - timedelta(minutes=1)}
    return jose_jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
```

The fix was to:
1. Remove all four in-function `from jose import ...` lines
2. Add a single `import jwt` at the top of the file
3. Replace `jose_jwt.encode(...)` → `jwt.encode(...)`

**Lesson: after any library migration, always grep for the old library name
across the entire codebase — including test files:**

```bash
grep -r "jose" .
```

Run this before committing to catch any remaining references in tests,
conftest, or other helper modules that the main code change might have missed.

---

## 4. PyJWT's stricter key-length warning

After migration, tests emitted this warning:

```
InsecureKeyLengthWarning: The HMAC key is 23 bytes long,
which is below the minimum recommended length of 32 bytes for SHA256.
See RFC 7518 Section 3.2.
```

`python-jose` accepted short keys silently. `PyJWT` actively warns when the
key is shorter than 32 bytes (256 bits), which is the minimum recommended
by RFC 7518 for HS256. This is a sign that PyJWT enforces better security
defaults, not a bug.

In the test environment, `SECRET_KEY` is intentionally short (from
`.env.example`). For production, the key must be at least 32 bytes —
ideally generated with `openssl rand -hex 32` (produces 64 hex characters =
32 bytes).

---

## 5. Issued tokens remain valid after migration

A common concern when switching JWT libraries: **will existing tokens stop
working?**

No. JWT tokens are encoded as RFC 7519-compliant Base64URL strings. The
format is:

```
<base64url(header)>.<base64url(payload)>.<base64url(signature)>
```

As long as the **algorithm** (HS256) and **secret key** are unchanged, any
library can verify a token any other library issued. The library is
transparent to the token format itself.

---

## 6. Interview-relevant points

**Q: Why is python-jose's `ecdsa` dependency a problem even if the app never
uses ECDSA?**
The dependency is installed into the environment regardless. Any automated
security scanner (pip-audit, Dependabot, Snyk) will flag it as a
vulnerability. "We don't call that code" is a valid engineering rationale but
not a valid response to a security audit — scanners don't do call-graph
analysis. Removing the dependency is the only way to silence the alert
permanently.

**Q: What does `cast(str, ...)` do at runtime?**
Nothing. `typing.cast(T, value)` is erased at runtime and returns `value`
unchanged. Its only purpose is to tell the static type checker (mypy) "treat
this value as type T." It was needed here because `python-jose`'s stubs typed
`encode()` as returning `str | bytes`, forcing a cast to satisfy mypy strict
mode. When the library's stubs are precise (as PyJWT's are), no cast is needed.

**Q: What is a transitive dependency and why does it matter?**
A direct dependency is one you explicitly list in `pyproject.toml`. A
transitive dependency is one your direct dependency needs — you didn't ask
for it, but it gets installed. `ecdsa` was never in this project's
`pyproject.toml`; it arrived via `python-jose`. Transitive dependencies are
a common source of surprise security alerts and are harder to upgrade
(you can't just bump the version — you have to wait for the direct dep to
update, or switch libraries as we did here).

---

## Related

- `docs/tech-debt.md` — TD-023 (now Resolved)
- PR #76 — migration commit history
- RFC 7518 Section 3.2 — minimum key length for HMAC-based JWTs
