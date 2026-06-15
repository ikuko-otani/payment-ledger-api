# S7-3: Domain Exceptions + Route-Layer Cleanup (TD-019/022/031)

> Date: 2026-06-15
> Branch: `feature/s7-3-domain-exceptions-route-cleanup`
> PR: #64

## Goal

Three related items of debt, all sub-items or relatives of TD-008
(repository/service-layer separation), were intentionally kept in a single
goal (not split), despite exceeding the 60–90min target:

- **TD-019**: service layer raises `fastapi.HTTPException` directly, coupling
  domain logic to the HTTP transport.
- **TD-022**: `accounts.py:create_account` and `audit_logs.py:get_audit_logs`
  embed ORM query logic and `log_action` calls directly in the route handler,
  bypassing the service layer that every other endpoint uses.
- **TD-031**: `create_user`'s duplicate-email check is a check-then-insert
  (TOCTOU) pattern — a genuine race surfaces as a raw 500 instead of 409.

DONE conditions (from the Sprint Tracker):

1. No `fastapi` import in the service layer (no direct `HTTPException` raises).
2. Domain exception classes defined and mapped to HTTP status via a single
   `@app.exception_handler`.
3. `accounts.create_account` and `audit_logs.get_audit_logs` go through the
   service layer (3-layer rule).
4. All tests green.
5. `create_user` always returns 409 on duplicate email — tested for both the
   pre-check path AND the race (`IntegrityError`) path.

---

## Step C-1: Add domain exception base classes + handler (TD-019)

💡 Before this step, every service that needed to signal "this request is
invalid" or "this conflicts with existing state" imported
`fastapi.HTTPException` directly. That couples the service layer to FastAPI —
a service can't be called from a script or unit-tested without an HTTP
context, and `HTTPException` carries HTTP concerns (`status_code`) into code
that should only know about *business* outcomes.

The fix: a small exception hierarchy in `app/core/exceptions.py`, with
`status_code` as a class attribute, and **one** handler registered for the
base class.

**`app/core/exceptions.py`** (new file):

```python
"""Domain-layer exceptions.

Services raise these instead of `fastapi.HTTPException` so they remain
usable (and unit-testable) without a FastAPI request context. `app/main.py`
registers a single `@app.exception_handler(DomainError)` that maps
`status_code` to an HTTP response.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for errors raised by the service layer."""

    status_code: int = 500

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class ValidationError(DomainError):
    """Request data is well-formed but violates a business rule. -> 422."""

    status_code = 422


class ConflictError(DomainError):
    """The request conflicts with existing state (e.g. duplicate). -> 409."""

    status_code = 409
```

**`app/main.py`** — register the handler once for the base class:

```python
from app.core.exceptions import DomainError


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
```

💡 Starlette's exception-handler lookup walks the **MRO** of the raised
exception class. Registering a handler only for `DomainError` is enough —
`ValidationError` and `ConflictError` (and any future subclass) are caught by
it automatically, because they inherit from `DomainError`. This avoided the
Notion page's suggested pattern of one class (and one handler) per case
(e.g. `AccountNotFoundError`), which would scale linearly with the number of
error cases. The trade-off: a generic `detail` string instead of a
machine-readable error code per case — acceptable for this project's
client (no programmatic error-handling on the frontend side yet).

⏱ ~10min

✅ Verification:
```bash
uv run pytest -q
```

```bash
git add app/core/exceptions.py app/main.py && git commit -m "feat(s7-3): add domain exception base classes and handler (TD-019)"
```

---

## Step C-2: Convert `currency_service`'s duplicate-rate error (TD-019)

💡 `create_exchange_rate` already had the right *shape* — catch
`IntegrityError` on `db.flush()` and convert it to a 409 — it just spelled
that 409 as `HTTPException`. This was the smallest possible first conversion:
one `except` block, one import swap.

**`app/services/currency_service.py`**:

```python
from app.core.exceptions import ConflictError

# ...

async def create_exchange_rate(
    db: AsyncSession,
    payload: ExchangeRateCreate,
    created_by: User,
) -> ExchangeRate:
    exchange_rate = ExchangeRate(
        from_currency_id=payload.from_currency_id,
        to_currency_id=payload.to_currency_id,
        rate=payload.rate,
        effective_date=payload.effective_date,
        created_by_id=created_by.id,
    )
    db.add(exchange_rate)
    try:
        await db.flush()
    except IntegrityError as e:
        raise ConflictError(
            detail="Exchange rate for this currency pair and date already exists"
        ) from e
    await db.refresh(exchange_rate)
    return exchange_rate
```

`from fastapi import HTTPException, status` was removed entirely from this
file — no other function in it used FastAPI.

⏱ ~10min

✅ Verification:
```bash
uv run pytest -q tests/test_currencies.py
```

```bash
git add app/services/currency_service.py && git commit -m "feat(s7-3): convert currency_service duplicate-rate error to ConflictError (TD-019)"
```

---

## Step C-3: Convert `transaction_service` validation errors (TD-019)

💡 This was the largest mechanical step: 8 separate
`raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=...)`
call sites, all becoming `raise ValidationError(detail=...)`. The 8 sites
were:

1. Unknown currency code (`_resolve_usd_conversion_rate`)
2. Base currency not found (`_resolve_usd_conversion_rate`)
3. No matching exchange rate (`_resolve_usd_conversion_rate`)
4. Unknown/inactive `account_id`s (`create_transaction`)
5. Missing debit/credit (`create_transaction`)
6. Mixed currency across entries (`create_transaction`)
7. Entry/account currency mismatch — TD-024 (`create_transaction`)
8. Unbalanced debit/credit (`create_transaction`)

**`app/services/transaction_service.py`** — import swap:

```python
from app.core.exceptions import ValidationError
```

Example of the mechanical replacement (site 8, unbalanced):

```python
# before
if debit_sum != credit_sum:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=f"Entries are not balanced: debit={debit_sum} credit={credit_sum}",
    )

# after
if debit_sum != credit_sum:
    raise ValidationError(
        detail=f"Entries are not balanced: debit={debit_sum} credit={credit_sum}"
    )
```

The same shape applied to the other 7 sites — only the `detail` message
differs per site.

⚠️ `_resolve_usd_conversion_rate`'s docstring said "Raises HTTP 422" — updated
to "Raises ValidationError" so the docstring doesn't lie about the new type.

**`tests/test_transactions.py`** — every
`with pytest.raises(HTTPException) as exc_info:` became
`with pytest.raises(ValidationError) as exc_info:` (7 occurrences). The
existing `exc_info.value.status_code` / `.detail` assertions kept working
unchanged, because `ValidationError` (via `DomainError`) exposes both
attributes — this is exactly the kind of "behavior-preserving from the
test's point of view" change that makes a large mechanical diff low-risk.

⏱ ~25min (largest step — 8 call sites + 7 test updates)

✅ Verification:
```bash
uv run pytest -q tests/test_transactions.py
grep -rn "from fastapi" app/services/
# -> should print nothing for transaction_service.py / currency_service.py
```

```bash
git add app/services/transaction_service.py tests/test_transactions.py && git commit -m "feat(s7-3): convert transaction_service validation errors to ValidationError (TD-019)"
```

---

## Step C-4: Fix `create_user`'s duplicate-email race (TD-031)

💡 The pre-fix code did `select(User)` (fetching the **full row**) just to
check existence, then `INSERT` — a classic check-then-insert (TOCTOU) gap.
Two concurrent requests with the same email can both pass the `SELECT`
before either commits; the loser's `INSERT` then violates `users.email`
UNIQUE and raises a raw `IntegrityError` → unhandled 500.

The fix has two layers:
1. **Narrow the pre-check** to `select(User.id)` — existence is all that's
   needed, no reason to fetch the whole row.
2. **Catch `IntegrityError` on `db.flush()`** as a fallback — this is what
   actually closes the race, converting the loser's failure to the same 409
   the pre-check would have given a non-racing duplicate.

**`app/services/user_service.py`**:

```python
"""User creation service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.schemas.user import UserCreate

_DUPLICATE_EMAIL_DETAIL = "Email already registered"


async def create_user(
    db: AsyncSession,
    payload: UserCreate,
    role: UserRole = UserRole.AUDITOR,
) -> User:
    # Pre-check: fast, friendly 409 for the common (non-racing) case.
    # Narrowed to User.id -- existence is all we need.
    result = await db.execute(select(User.id).where(User.email == payload.email))
    if result.scalar_one_or_none() is not None:
        raise ConflictError(detail=_DUPLICATE_EMAIL_DETAIL)

    hashed = await get_password_hash(payload.password)
    user = User(email=payload.email, hashed_password=hashed, role=role)
    db.add(user)

    # Race fallback: two concurrent requests can both pass the pre-check
    # above before either commits. The users.email UNIQUE constraint
    # catches that case here -- without this, the loser would surface as a
    # raw 500 IntegrityError instead of 409.
    try:
        await db.flush()
    except IntegrityError as e:
        raise ConflictError(detail=_DUPLICATE_EMAIL_DETAIL) from e

    await db.refresh(user)
    return user
```

**`tests/test_users.py`** — new concurrency test, reproducing the race
**without mocking** by running two independent `AsyncSession`s from the same
`engine` fixture via `asyncio.gather`:

```python
import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import ConflictError
from app.models.user import User
from app.schemas.user import UserCreate
from app.services import user_service


@pytest.mark.asyncio
async def test_create_user_concurrent_duplicate_email_returns_conflict(
    engine: AsyncEngine,
) -> None:
    """TOCTOU race (TD-031): two concurrent create_user calls with the same
    email both pass the pre-check SELECT (neither has committed yet), so
    both proceed to INSERT. The users.email UNIQUE constraint lets exactly
    one succeed; the loser's flush() raises IntegrityError, which
    create_user converts to ConflictError instead of a raw 500.
    """
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    payload = UserCreate(email="race@example.com", password="secret123")

    async def _attempt() -> User | ConflictError:
        async with session_factory() as session:
            try:
                user = await user_service.create_user(session, payload)
                await session.commit()
                return user
            except ConflictError as e:
                await session.rollback()
                return e

    results = await asyncio.gather(_attempt(), _attempt())

    successes = [r for r in results if isinstance(r, User)]
    conflicts = [r for r in results if isinstance(r, ConflictError)]

    assert len(successes) == 1
    assert len(conflicts) == 1
```

⚠️ Each `_attempt()` needs its **own** `AsyncSession` — a single shared
session can't have two in-flight statements at once. `async_sessionmaker`
bound to the shared `engine` fixture gives each task an independent
connection, so the two `INSERT`s genuinely race at the database level.

The pre-existing `test_register_user_duplicate_email_returns_409` (HTTP
level, sequential requests) already covers the pre-check path — together the
two tests satisfy DONE condition 5 (both pre-check and race paths return
409).

⏱ ~20min

✅ Verification:
```bash
uv run pytest -q tests/test_users.py
```

```bash
git add app/services/user_service.py tests/test_users.py && git commit -m "fix(s7-3): handle create_user duplicate-email race via ConflictError (TD-031)"
```

---

## Step C-5: Extract `create_account` into `account_service` (TD-022)

💡 Every other "create X" endpoint (`create_transaction`, `create_user`,
`create_currency`, `create_exchange_rate`) already delegated to a service
function. `accounts.py:create_account` was the odd one out — it ran
`db.add(...)`, `await db.flush()`, and `log_action(...)` directly inside the
route handler. The inconsistency itself was the debt (TD-022): not a bug, but
a "why is this one different?" red flag.

**`app/services/account_service.py`** (new file):

```python
"""Account creation service."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.user import User
from app.schemas.account import AccountCreate
from app.services.audit_service import log_action


async def create_account(
    db: AsyncSession,
    payload: AccountCreate,
    current_user: User,
) -> Account:
    account = Account(
        code=payload.code,
        name=payload.name,
        account_type=payload.account_type,
        currency=payload.currency,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)

    after_value: dict[str, Any] = {
        "id": str(account.id),
        "code": account.code,
        "name": account.name,
        "account_type": account.account_type.value,
        "currency": account.currency,
    }
    await log_action(
        db,
        user_id=current_user.id,
        entity_type="account",
        entity_id=account.id,
        action="create",
        before=None,
        after=after_value,
    )
    return account
```

**`app/api/v1/routes/accounts.py`** — the route shrinks to HTTP plumbing only:

```python
@router.post("", response_model=AccountRead, status_code=201)
async def create_account(
    payload: AccountCreate,
    db: DbDep,
    current_user: AdminUser,
) -> Account:
    return await account_service.create_account(db, payload, current_user)
```

This was a **behavior-preserving refactor** — no logic changed, only its
location. The existing `tests/test_accounts.py` HTTP-level tests act as
regression tests: unchanged pass/fail confirms the extraction didn't alter
behavior.

⏱ ~15min

✅ Verification:
```bash
uv run pytest -q tests/test_accounts.py
```

```bash
git add app/services/account_service.py app/api/v1/routes/accounts.py && git commit -m "refactor(s7-3): extract create_account into account_service (TD-022)"
```

---

## Step C-6: Extract `get_audit_logs` query into `audit_service` (TD-022)

💡 Same pattern as Step C-5, applied to `audit_logs.py:get_audit_logs` — the
filtering/ordering/pagination `select(AuditLog)...` query lived directly in
the route handler.

**`app/services/audit_service.py`** — added `list_audit_logs` alongside the
existing `log_action`:

```python
async def list_audit_logs(
    db: AsyncSession,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[AuditLog]:
    filters = []
    if entity_type:
        filters.append(AuditLog.entity_type == entity_type)
    if entity_id:
        filters.append(AuditLog.entity_id == entity_id)
    if from_dt:
        filters.append(AuditLog.created_at >= from_dt)
    if to_dt:
        filters.append(AuditLog.created_at <= to_dt)

    stmt = (
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
```

**`app/api/v1/routes/audit_logs.py`** — route delegates entirely:

```python
@router.get("", response_model=list[AuditLogRead])
async def get_audit_logs(
    db: DbDep,
    _current_user: AdminUser,
    entity_type: str | None = Query(default=None),
    entity_id: uuid.UUID | None = Query(default=None),
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AuditLog]:
    return await audit_service.list_audit_logs(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=limit,
        offset=offset,
    )
```

⚠️ `select` is no longer imported directly in `audit_logs.py` — it moved
entirely into `audit_service.py`. Leaving an unused import would have failed
the `ruff check` pre-pytest step.

⏱ ~15min

✅ Verification:
```bash
uv run pytest -q tests/test_audit_log.py tests/test_audit_logs_endpoint.py
```

```bash
git add app/services/audit_service.py app/api/v1/routes/audit_logs.py && git commit -m "refactor(s7-3): extract audit-log query into audit_service.list_audit_logs (TD-022)"
```

---

## Step C-7: tech-debt.md + concept note + final verification

Moved TD-019, TD-022, and TD-031 from "Open Items" to "Resolved" in
`docs/tech-debt.md`, each entry summarizing the fix.

Also wrote a concept note explaining *why* TD-022 mattered, prompted by a
question during Step C-5/6 about why the extraction was worth doing:
[[three-layer-architecture-route-vs-service]]
(`docs/learning-notes/concepts/three-layer-architecture-route-vs-service.md`).
It covers the api→services→models rule, before/after `create_account` code,
unit-testability and reusability arguments, and a PHP/MVC
Fat-Controller→Skinny-Controller comparison.

Final full suite run:

```bash
uv run pytest -q
grep -rn "from fastapi" app/services/
```

```bash
git add docs/tech-debt.md && git commit -m "docs(tech-debt): move TD-019/022/031 to Resolved (S7-3)"
git add docs/learning-notes/concepts/three-layer-architecture-route-vs-service.md && git commit -m "docs(s7-3): add concept note on route vs service layer split (TD-022)"
```

✅ All 5 DONE conditions met → PR #64 created and merged.

---

## Key takeaways

- I learned that registering a single `@app.exception_handler(DomainError)`
  is enough to cover every subclass (`ValidationError`, `ConflictError`,
  and any future one), because Starlette's exception-handler lookup walks the
  exception's MRO. I had expected to need one handler per error type.
- I learned the check-then-insert (TOCTOU) shape directly from TD-031: a
  pre-check `SELECT` is good for UX (fast, friendly 409 in the common case),
  but only a `try`/`except IntegrityError` around the actual `INSERT`/`flush`
  closes the race for real. The two layers serve different purposes and both
  are worth keeping.
- I learned how to write a real (non-mocked) concurrency test: two
  independent `AsyncSession`s from the same `engine` fixture, driven with
  `asyncio.gather`, genuinely race two `INSERT`s against the same UNIQUE
  constraint. This is a pattern I'd reuse for any future "what happens under
  a race" test.
- What I'd do differently: Step C-3 (8 call sites in
  `transaction_service.py` + 7 test updates) was the biggest single step and
  took longer than the ~25min estimate suggested it would feel like in
  practice, mostly because each site needed a quick read to confirm the
  `detail` message carried over correctly. Next time, a step with this many
  near-identical mechanical edits might be worth splitting into "convert
  service" and "convert tests" as two separate commits/steps, even though
  they're both small.
- What surprised me: TD-022 (the route-cleanup item) felt like the smallest
  problem of the three TDs going in, but the resulting concept note
  ([[three-layer-architecture-route-vs-service]]) turned out to be one of the
  most reusable artifacts from this goal — it directly explains *why* the
  api→services→models rule exists, which I expect to reference again whenever
  a new "fat route" shows up.
- Worth remembering for future goals: when converting a large mechanical
  block of `raise HTTPException(...)` → `raise SomeDomainError(...)`, the
  existing tests' `.status_code`/`.detail` assertions kept working unchanged
  because `DomainError` exposes the same attributes — designing the new
  exception's interface to match what callers already expect made this a
  true behavior-preserving refactor from the test's point of view.

## Related

- [[three-layer-architecture-route-vs-service]] — concept note written during
  this goal (TD-022 rationale).
- `docs/tech-debt.md` — TD-019, TD-022, TD-031 (Resolved, S7-3).
- `app/core/exceptions.py` — `DomainError`/`ValidationError`/`ConflictError`
  hierarchy.
- `CLAUDE.md` §9 — File Placement Notes (3-layer rule).
