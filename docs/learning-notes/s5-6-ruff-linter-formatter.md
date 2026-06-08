# S5-6: ruff Linter / Formatter Configuration

**Date**: 2026-06-08
**Branch**: `feature/s5-6-ruff-linter-formatter`
**Goal**: Introduce ruff linter/formatter, unify code style across the codebase,
and add `make lint` / `make format` targets before mypy strict (S5-7).

---

## Step C Walkthrough

### Overview of violations found (27 total before ignore additions)

| Rule | Count | Action |
|------|-------|--------|
| `B008` | 11 | Added to `ignore` — FastAPI `Depends`/`Query` pattern |
| `UP042` | 4 | Added to `ignore` — `StrEnum` migration unsafe for SQLAlchemy |
| `UP017` | 8 | Auto-fixed (`--fix`) — `datetime.timezone.utc` → `datetime.UTC` |
| `UP037` | 1 | Auto-fixed (`--fix`) — remove quoted type annotation |
| `B904` | 2 | Manual fix — add `raise ... from e` in `deps.py`, `currency_service.py` |
| `B905` | 1 | Manual fix — add `strict=True` to `zip()` in `transaction_service.py` |

### Rule groups selected

```toml
[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP", "B", "SIM"]
ignore = ["E501", "B008", "UP042"]
```

| Group | Purpose |
|-------|---------|
| `E` / `W` | pycodestyle errors and warnings |
| `F` | pyflakes (undefined names, unused imports) |
| `I` | isort (import ordering) |
| `UP` | pyupgrade (modernize Python syntax to 3.12) |
| `B` | flake8-bugbear (likely bugs, design issues) |
| `SIM` | flake8-simplify (simplify redundant patterns) |

### Why `B008` must be ignored in FastAPI projects

FastAPI uses function calls (`Depends(get_db)`, `Query(None)`) as default argument
values — this is the core dependency injection mechanism. ruff's `B008` flags any
function call in default arguments as a potential bug, but in FastAPI this is
intentional. Without ignoring `B008`, every route handler triggers a false positive.

### Why `UP042` is ignored for SQLAlchemy enums

`UP042` suggests replacing `class Foo(str, Enum)` with `class Foo(StrEnum)`.
`StrEnum` (Python 3.11+) changes `__str__` behavior: with `str, Enum`,
`str(AccountType.SAVINGS)` returns `"AccountType.SAVINGS"`, but with `StrEnum`
it returns `"savings"`. SQLAlchemy stores enum values as strings, so this change
could silently alter the values written to the database. ruff marks it as an
unsafe fix for this reason.

### The `--statistics` vs `--fix` count discrepancy

Running `ruff check . --statistics` showed 12 errors, but `ruff check . --fix`
reported "21 errors found, 18 fixed". The extra 9 came from isort (`I`) fixes
that were triggered as a cascade: when `UP017` rewrote `datetime.timezone.utc`
to `datetime.UTC`, the import statements changed, which triggered isort
re-ordering fixes in the same files. The fix pass counts each individual
violation including the cascaded ones.

### `ruff format .` — 18 files reformatted

`ruff format` uses `line-length = 88` (Black default) and reformatted 18 files.
This is expected on first application to a codebase that previously used
`line-length = 100`. The 51 files that were already formatted needed no changes.

---

## Key Takeaways

### What did I learn?

I learned how ruff consolidates three separate tools — flake8, black, and isort —
into a single Rust-based linter/formatter configured entirely within `pyproject.toml`.
I also learned the meaning of each rule group (`UP`, `B`, `SIM` were new to me) and
why `line-length = 88` is the de facto standard inherited from Black.

I saw firsthand that applying new rules to an existing codebase generates a burst of
violations that need to be triaged: some are false positives for the framework being
used (`B008`), some are unsafe to auto-apply (`UP042`), and some are genuine
improvements that are quick to fix manually (`B904`, `B905`).

### What would I do differently?

I would not add `[tool.coverage.run] concurrency = ["asyncio", "thread"]` without
first verifying that `asyncio` is a valid value for coverage.py's `concurrency`
setting. It is not — valid values are `thread`, `gevent`, `greenlet`, `eventlet`,
and `multiprocessing`. That mistake broke the CI test job and required a follow-up
commit to remove it. I should look up the coverage.py documentation before applying
TD fixes rather than going from memory.

### What surprised me?

I was surprised that `ruff check . --fix` reported more total errors (21) than
`ruff check . --statistics` had shown (12). I expected them to match. Understanding
that auto-fixes can cascade — one fix triggering a re-scan that finds new violations
in the same file — was a useful insight into how ruff's fix pass works internally.

I was also surprised that `ruff format .` reformatted 18 files when CI had been green
(lint-wise) before this goal. "No lint errors" and "consistently formatted" are two
different things.

### What is worth remembering for future goals?

- **Always ignore `B008` in FastAPI projects.** It fires on every route handler.
- **`UP042` (`StrEnum`) is unsafe for SQLAlchemy enum columns.** The `__str__`
  change can silently alter database-stored values. Keep `str, Enum` until a
  deliberate migration is planned.
- **`coverage.py` `concurrency` does not support `asyncio`.** Valid values are
  `thread`, `gevent`, `greenlet`, `eventlet`, `multiprocessing`. TD-013
  (async coverage under-reporting) needs a different approach.
- **`ruff format` and `ruff check` are independent.** Passing lint does not mean
  the code is formatted to ruff's style. Run both before a PR.
- **`make check`** (format → lint → typecheck in sequence) is the right pre-push
  habit now that the Makefile exists.

---

## Related

- `docs/adr/` — no new ADR for this goal (tooling config, not architecture)
- `docs/tech-debt.md` — TD-013 remains open (asyncio coverage approach TBD)
