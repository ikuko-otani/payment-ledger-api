# S8-4: Dead Code Cleanup — balance.py / ledger_service.py (TD-036 / TD-037)

**Date**: 2026-06-21
**Branch**: feature/s8-4-dead-code-cleanup
**PR**: #85

---

## What we did

Removed two dead-code files left behind by the S7-8 repository layer migration (PR #81):

1. **Migrated `tests/test_balance.py`** — four service-layer tests called `calculate_balance()` from `app/services/balance.py` directly. Rewrote each call to use `SQLAlchemyAccountRepository(db_session).calculate_balance()` so the tests now exercise the same code path as production.

2. **Deleted `app/services/balance.py`** — `calculate_balance()` had been replaced by `SQLAlchemyAccountRepository.calculate_balance()` since S7-8. Only the test file was still importing it.

3. **Deleted `app/services/ledger_service.py`** — `get_ledger_entries()` had no test imports and no production callers after `LedgerRepository.list_entries()` took over in S7-8. Straight deletion, no test migration required.

4. **Closed TD-036 / TD-037** in `docs/tech-debt.md`.

5. **Fixed pip-audit CI failure** — `msgpack` 1.1.2 → 1.2.1 (GHSA-6v7p-g79w-8964) and `pydantic-settings` 2.14.0 → 2.14.2 (GHSA-4xgf-cpjx-pc3j) upgraded via `uv lock --upgrade-package`.

---

## Step C walkthrough

### Step 1 — Rewrite imports in `tests/test_balance.py`

Replace:
```python
from app.services.balance import calculate_balance
```
With:
```python
from app.repositories.account_repository import SQLAlchemyAccountRepository
```

### Step 2 — Rewrite four service-layer test call sites

Pattern change:
```python
# before
result = await calculate_balance(db_session, cash.id, datetime(...))

# after
result = await SQLAlchemyAccountRepository(db_session).calculate_balance(
    cash.id, datetime(...)
)
```

Key point: the `db` argument moves from the first positional arg of the function to the constructor, and `account_id` becomes the first arg of `calculate_balance()`.

### Step 3 — Delete `app/services/balance.py`

```bash
git rm app/services/balance.py
```

### Step 4 — Delete `app/services/ledger_service.py`

```bash
git rm app/services/ledger_service.py
```

### Step 5 — Move TD-036 / TD-037 to Resolved in `docs/tech-debt.md`

### Step 6 — Fix pip-audit CI failure (unplanned)

```bash
uv lock --upgrade-package msgpack --upgrade-package pydantic-settings
uv sync --all-groups
uv run pip-audit  # → No known vulnerabilities found
```

---

## Key takeaways

**What did I learn?**

I learned the correct sequence for removing dead code that still has test references: migrate the tests first, verify they pass, then delete the source file. Deleting first causes an immediate `ImportError` that breaks the test suite. The order matters.

I also learned to check for import references before deciding whether a file needs test migration. `ledger_service.py` had no test imports, so it could be deleted directly. `balance.py` did, so it needed a migration step first. Running a quick `grep -rn "from app.services.balance"` before planning saves time.

**What would I do differently?**

I would run `uv run pip-audit` locally before pushing the PR, not just `uv run poe check`. The CI `lint` job includes `pip-audit` but the local `poe check` alias does not — this gap caused an avoidable CI failure. Worth noting as a pre-PR habit.

**What surprised me?**

The argument signature change when moving from a standalone function to a repository method was subtle. `calculate_balance(db, account_id, as_of)` became `SQLAlchemyAccountRepository(db).calculate_balance(account_id, as_of)` — the `db` disappears from the call site and moves to the constructor. Easy to miss when doing a find-and-replace.

**What is worth remembering for future goals?**

- Always grep for all import sites before planning a dead-code removal — it determines whether test migration is needed.
- `pip-audit` runs in CI lint but not in local `poe check`. Run it manually before pushing if any `uv.lock` changes are on the branch, or if time has passed since the last lock file update.
- Dead code left by a refactor (like the S7-8 repository migration) should be cleaned up in a dedicated follow-up goal rather than bundled into the refactor itself — keeps the refactor PR focused and reviewable.
