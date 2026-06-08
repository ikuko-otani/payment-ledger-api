# S5-7: mypy strict Across All Files

**Date**: 2026-06-08
**Branch**: `feature/s5-7-mypy-strict`
**Goal**: Enable `strict = true` in `[tool.mypy]`, remove the per-module
`ignore_errors` overrides left over from earlier sprints, fix every resulting
type error in `app/`, and add a mypy step to CI.

---

## Step C Walkthrough

### Scope was smaller than expected (7 errors → 14 errors → 0)

The S5-6 handoff predicted "a large batch of type errors" once strict mode was
turned on. Running `mypy app/ --strict` against the *existing* config showed
only 7 errors — but that was misleading: the existing
`[[tool.mypy.overrides]] ignore_errors = true` for 4 modules
(`app.db.session`, `app.services.balance`, `app.models.transaction`,
`app.dependencies.idempotency`) was still silently suppressing errors in those
files. Re-running with a clean `strict = true` config (no overrides) surfaced
the real picture: **9 files, 14 errors**. Earlier sprints had already written
fairly careful type hints, so the actual remaining gap was small.

### Error categories and fixes

| Category | Files | Fix |
|---|---|---|
| `no-untyped-def` | `main.py`, `schemas/transaction.py` | Added `-> dict[str, str]` / `-> int` return annotations |
| `type-arg` | `models/transaction.py`, `middleware/logging.py` | `dict` → `dict[str, Any]`, `Callable` → `Callable[[Request], Awaitable[Response]]` |
| `no-any-return` | `core/security.py`, `services/balance.py` | Wrapped third-party return values (`jwt.encode`, `scalar_one`) in `cast(str, ...)` / `cast(int, ...)` |
| `misc` (async generator return type) | `db/session.py`, `dependencies/idempotency.py` | Changed `-> AsyncSession` / `-> aioredis.Redis` to `-> AsyncGenerator[T, None]` |
| `unused-ignore` | `core/cache.py`, `dependencies/idempotency.py` | Removed 6 stale `# type: ignore[type-arg]` comments |

### `pyproject.toml` changes

```toml
[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
```

Two things were removed alongside adding `strict = true`:
- `warn_return_any = false` — keeping it would have made `uv run mypy app/`
  (no CLI flag) silently pass the `no-any-return` errors that
  `mypy app/ --strict` (CLI flag always wins) would still report. Removing it
  keeps the two commands consistent and forced an honest fix of the 2
  `no-any-return` errors.
- The 4-module `ignore_errors = true` override block — the entire point of
  S5-7 was to apply strict checking to *all* files, so leaving any module
  exempted would have defeated the goal.

### Why the `# type: ignore[type-arg]` comments became unused

The S5-6 handoff explicitly warned *not* to remove these comments
(`redis.asyncio` type stubs were assumed incomplete). But `warn_unused_ignores`
(part of `strict`) flagged all 6 of them as unused. Investigation showed:
- `redis` is currently pinned at v7.4.0 and ships `py.typed`
- `redis.asyncio.Redis` is generic but its type parameter now has a default,
  so writing a bare `aioredis.Redis` annotation no longer triggers `[type-arg]`

The suppressions were added back in S2-3 / S5-5, presumably when the
installed `redis` version had weaker type stubs. They had quietly become dead
weight — a good example of how `# type: ignore` comments need periodic
re-validation as dependencies are upgraded. This contradicted the prior
handoff note, but the tool (`warn_unused_ignores`) was the more reliable
source of truth than the stale assumption.

### `cast()` vs runtime conversion

For `no-any-return` errors at library boundaries (`jwt.encode()` returning
`Any`, `Result.scalar_one()` returning `Any`), `cast(str, ...)` /
`cast(int, ...)` was used rather than `str(...)` / `int(...)`. `cast()` is a
pure type-checker hint with zero runtime cost — it tells mypy "trust me, this
is already the right type," which is appropriate when the underlying value is
known to be correct and the looseness is purely a type-stub gap, not an actual
runtime ambiguity.

### CI integration

Added the mypy step to the existing `lint` job (alongside `ruff check`) rather
than creating a separate job — both are static-analysis steps with no
dependency on the Postgres/Redis services that the `test` job needs, so they
run fast and in parallel with nothing to wait for.

```yaml
- name: Type check with mypy
  run: uv run mypy app/
```

### Side discovery: `make` doesn't run on Windows

`make typecheck` (introduced in S5-6) failed with "command not found" on the
Windows host — `make` isn't available without a separate install. The
underlying `uv run mypy app/` worked fine. Recorded as **TD-014**.

### Side discovery: TD-013's proposed fix was already tried and reverted

While reviewing tech debt, found that TD-013's suggested fix
(`[tool.coverage.run] concurrency = ["asyncio", "thread"]`) had actually been
attempted in S5-6 (`b009592`) and reverted in the same sprint (`d9446d6`)
because `asyncio` is not a valid `concurrency` value (`coverage.py` only
accepts `thread`/`gevent`/`greenlet`/`eventlet`/`multiprocessing`). Updated
TD-013 to record this so the Fix suggestion isn't tried again from scratch.

---

## Key Takeaways

### What did I learn?

I learned that `strict = true` is a bundle of ~13 individual flags
(`disallow_untyped_defs`, `disallow_any_generics`, `warn_return_any`,
`warn_unused_ignores`, etc.), and that seeing each error category mapped
cleanly onto one of these flags made the otherwise abstract "strict mode"
concept concrete. I also learned the precise difference between an async
generator's declared return type (`AsyncGenerator[T, None]`) and the type of
the value it yields — a distinction that doesn't really exist in PHP-style
generators and that the type checker enforces correctly once you write it the
right way.

### What would I do differently?

I'd run the *real* strict check (without the existing per-module
`ignore_errors` overrides) before estimating the goal's size, rather than
trusting the handoff note's "expect a lot of errors" framing. The first
`mypy app/ --strict` run under the old config reported only 7 errors and would
have under-sold the actual scope (14 across 9 files) if I hadn't dug one level
deeper to check whether the overrides were still active.

### What surprised me?

That two of the S5-6 handoff's explicit warnings turned out to be stale by the
time I acted on them: (1) the `# type: ignore[type-arg]` comments that were
"intentional, do not remove" turned out to be unused dead weight once
`warn_unused_ignores` ran against the current `redis` version, and (2) TD-013's
suggested fix had already been tried and reverted in the very same sprint that
wrote the handoff note. Both cases reinforced that a tool's live output
(`mypy`'s `unused-ignore` diagnostic, `git log -S`) is a more trustworthy
source of truth than a recently-written assumption — assumptions decay fast
even across a single sprint boundary.

### What is worth remembering for future goals?

`# type: ignore` comments are not "set and forget" — they should be
re-validated whenever the underlying dependency is upgraded, because type
stubs improve over time and stale suppressions silently accumulate. Also,
before trusting a tech-debt entry's "Fix:" suggestion, it's worth a quick
`git log -S <keyword>` to check whether that exact fix was already attempted
and reverted — it can save a repeat of already-known-bad work.

---

## Related

- [TD-014](../tech-debt.md) — `Makefile` not runnable on Windows host
- [TD-013](../tech-debt.md) — corrected: `asyncio` is not a valid
  `coverage.py` `concurrency` value (tried & reverted in S5-6)
- [s5-6-ruff-linter-formatter.md](./s5-6-ruff-linter-formatter.md) — prior
  goal that scaffolded `make typecheck` and surfaced the override list this
  goal removed
