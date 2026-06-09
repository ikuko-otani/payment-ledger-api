# S6-2: pytest-cov Coverage Audit

**Date**: 2026-06-09
**Goal**: Measure current test coverage with pytest-cov and identify gaps below 85%.

---

## Step C Walkthrough

### What was implemented

Added `addopts` to `[tool.pytest.ini_options]` in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
addopts = "--cov=app --cov-report=term-missing --cov-fail-under=85"
```

This ensures that every `uv run pytest` invocation (local and CI) automatically
runs with coverage reporting and fails if overall coverage drops below 85%.

**Design note — why `addopts` instead of CLI flags only**:
`addopts` centralises the coverage configuration so that developers, CI, and IDE
test runners all use the same flags without manual coordination. CI keeps its
extra `-v --tb=short` flags via the command line; pytest merges them with
`addopts` at runtime.

**Threshold rationale (TD-013)**:
`coverage.py` under-reports async function coverage (see TD-013 in tech-debt.md).
85% is a conservative threshold that absorbs the known false-negative rate while
still catching genuine regressions. The threshold should be re-evaluated when
`--cov-branch` is introduced.

---

## Coverage Results (2026-06-09)

### Overall Coverage

| Metric | Value |
|--------|-------|
| Total statements | 855 |
| Covered statements | 772 |
| Overall coverage % | 90.29% |
| Test count | 96 passed, 2 warnings |
| Run time | ~3 min 49 s |

### Modules Below 85%

| Module | Cover% | Stmts | Miss | Missing Lines |
|--------|--------|-------|------|---------------|
| `app/db/session.py` | 46% | 13 | 7 | 29–35 |
| `app/services/user_service.py` | 53% | 17 | 8 | 21–36 |
| `app/services/currency_service.py` | 59% | 39 | 16 | 22, 33–34, 43–51, 69–75 |
| `app/api/v1/routes/auth.py` | 71% | 17 | 5 | 23–30 |
| `app/main.py` | 79% | 24 | 5 | 18–21, 38 |
| `app/services/transaction_service.py` | 79% | 63 | 13 | 56–92 |
| `app/core/deps.py` | 80% | 40 | 8 | 36, 41–46, 66 |

---

## Gap Classification

### Category 1: Error Handling Paths (HTTPException, try/except)

Happy paths are covered; exception branches are not exercised.

| File | Lines | Description |
|------|-------|-------------|
| `app/api/v1/routes/auth.py` | 23–28 | `401 Unauthorized` — unknown email or wrong password |
| `app/services/user_service.py` | 21–25 | `409 Conflict` — duplicate email on user create |
| `app/services/currency_service.py` | 69–73 | `409 Conflict` — duplicate exchange rate (IntegrityError) |
| `app/services/transaction_service.py` | 57–61 | `422` — unknown currency code |
| `app/services/transaction_service.py` | 66–70 | `422` — USD not found in currencies table |
| `app/services/transaction_service.py` | 81–87 | `422` — no exchange rate for requested date |

### Category 2: Auth / Permission Failures

Defensive code in `get_current_user` and role-check dependencies is almost
entirely untested.

| File | Lines | Description |
|------|-------|-------------|
| `app/core/deps.py` | 36 | JWT `sub` claim is `None` → `401` |
| `app/core/deps.py` | 42–43 | User not found in DB (deleted user) → `401` |
| `app/core/deps.py` | 44–45 | `is_active=False` user → `401` |
| `app/core/deps.py` | 66 | `require_auditor_or_admin` role check failure → `403` |

### Category 3: Boundary / Edge Cases

| File | Lines | Description |
|------|-------|-------------|
| `app/services/currency_service.py` | 43–51 | Filter combinations in `get_exchange_rates` (`from_currency_id` / `to_currency_id` / `effective_date` independently or combined) |
| `app/services/transaction_service.py` | 89–92 | Non-USD amount conversion math (`ROUND_HALF_UP`) |

### Category 4: Infrastructure / Startup Paths

Intentionally uncovered due to test architecture. Low priority for S6-3.

| File | Lines | Description |
|------|-------|-------------|
| `app/main.py` | 18–21 | `lifespan()` body — structlog / OpenTelemetry setup. Test client does not invoke lifespan. |
| `app/main.py` | 38 | `/health` endpoint response line — no health check test exists |
| `app/db/session.py` | 29–35 | `get_db()` commit/rollback body — tests use their own session fixtures; `get_db` is never called |

### Category 5: TD-013 (async false negatives)

Lines immediately after `await` expressions or inside `async for`/`yield` are
mis-reported as uncovered by `coverage.py`. These paths are very likely executed
at runtime. Treat as lowest priority in S6-3.

**How to identify TD-013**: the line containing `await X` is marked covered, but
the very next line (result assignment or continuation logic) is marked missed.

| File | Lines | Description |
|------|-------|-------------|
| `app/api/v1/routes/auth.py` | 29–30 | `token = create_access_token(...)` and `return` — immediately after `await db.execute()` |
| `app/services/currency_service.py` | 22, 33–34 | `return` in `get_currencies`; `flush`/`refresh` in `create_currency` |
| `app/services/user_service.py` | 28–36 | Entire happy path of `create_user` — continuation after `await db.execute()` |
| `app/core/deps.py` | 41 | `user = user_result.scalar_one_or_none()` — immediately after `await db.execute()` |
| `app/db/session.py` | 29–35 | `yield` in async generator (classic TD-013 pattern) |

---

## S6-3 Priority Order

| Priority | Category | Rationale |
|----------|----------|-----------|
| High | Error handling paths | Real test gaps; bugs can hide in unexercised exception branches |
| High | Auth / permission failures | Security-critical paths with no test verification |
| Medium | Boundary / edge cases | Can affect correctness of filter logic and currency math |
| Low | Infrastructure / startup | Hard to cover with current test architecture; runtime verified differently |
| Lowest | TD-013 false negatives | Likely executed at runtime; investigate only if suspicious |

---

## Key Takeaways

### What did I learn?

I learned that `addopts` in `[tool.pytest.ini_options]` is the right place to
put coverage flags that should apply universally — local dev, CI, and IDE test
runners all pick them up automatically without any coordination. I also learned
how to read a `--cov-report=term-missing` table: the `Missing` column gives
exact line numbers, which makes it straightforward to open the file and
understand which execution paths have never been exercised.

I learned to distinguish five categories of coverage gaps: error handling paths,
auth/permission failures, boundary/edge cases, infrastructure/startup paths, and
TD-013 async false negatives. That classification turned out to be more useful
than a raw list of line numbers, because it directly maps to what kind of test
needs to be written in S6-3.

### What would I do differently?

I would run the coverage audit earlier in the sprint (before S6, not in S6-2)
so that the gap classification could inform test design from the beginning. The
"measure first, then supplement" order enforced by S6-2 → S6-3 is good
discipline, but discovering that `get_db()` has 46% coverage only because tests
bypass it entirely (not because it is untested logic) would have been useful
context when writing earlier tests.

### What surprised me?

The 46% coverage on `app/db/session.py` was surprising at first. The `get_db()`
function looks trivial, but its entire body (lines 29–35: the `async with`
context, `yield`, commit, and rollback) is unreachable from tests because every
test fixture injects its own session directly. This is intentional — test
isolation requires bypassing `get_db` — but coverage.py has no way to know that.
It reads as a gap even though the function itself is not the thing being tested.

Similarly, TD-013 caused `app/services/user_service.py` to report 53% coverage
even though `create_user` is called by the HTTP tests. The async continuation
lines after `await db.execute()` were marked missed despite executing at runtime.

### What is worth remembering for future goals?

1. **TD-013 signature**: `await X` line is marked covered, but the very next
   assignment or conditional is marked missed. This is a false negative —
   investigate actual test coverage before writing a new test for that line.

2. **`--cov-fail-under` threshold**: set conservatively (85%, not 90%+) when
   TD-013 affects async-heavy code. The threshold is a regression guard, not a
   goal in itself.

3. **Gap classification framework** (reusable for future audit goals):
   error handling → auth failures → boundary cases → infrastructure → TD-013.
   Apply this order to prioritise S6-3 test additions.

4. **`get_db()` coverage is structurally low** in this codebase and will remain
   so. Do not treat it as a test gap requiring new tests — the session lifecycle
   is covered by the fixture design, not by calling `get_db` directly.
