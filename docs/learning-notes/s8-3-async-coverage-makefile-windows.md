# S8-3: Async Coverage Fix and Cross-Platform Task Runner (TD-013/014)

**Date**: 2026-06-20
**Branch**: feature/s8-3-async-coverage-makefile-windows
**Goal**: Fix async coverage under-reporting via sys.monitoring (TD-013); replace Makefile with poethepoet for cross-platform task running (TD-014).

---

## Step C Walkthrough

### Overview

Two independent improvements to the project's tooling:

| TD | Problem | Fix |
|----|---------|-----|
| TD-013 | Lines after `await` not recorded by `sys.settrace` → coverage under-reported | `[tool.coverage.run] core = "sysmon"` in `pyproject.toml` |
| TD-014 | `Makefile` unusable on Windows (no `make` installed) | Replace with `poethepoet` tasks, run via `uv run poe <task>` |

---

### TD-013: async coverage under-reporting

#### Why `sys.settrace` misses `await` resumption

Python's traditional coverage mechanism hooks into `sys.settrace`, which fires three event types:
- `call` — function entered
- `line` — each line about to execute
- `return` / `exception` — function leaving

When an `async` function hits `await`, the coroutine is **suspended** and control returns to the event loop. When the event loop resumes the coroutine (after the awaited result is ready), Python re-enters the coroutine body — but **does not re-fire `sys.settrace`**. The line immediately after `await` executes with no trace hook registered, so coverage never records it.

Example: in `app/dependencies/idempotency.py`, the `yield ctx` line suspends during the route handler execution. The lines after `yield` in the `except` block can appear uncovered even when they execute.

#### How `sys.monitoring` (PEP 669, Python 3.12) fixes this

Python 3.12 introduced `sys.monitoring` as a replacement for `sys.settrace`. It fires events at the **bytecode instruction level**, including on coroutine resume (`RESUME` opcode). Coverage.py 7.2+ can use this backend by setting `COVERAGE_CORE=sysmon`; the equivalent `pyproject.toml` config is:

```toml
[tool.coverage.run]
source = ["app"]
core = "sysmon"
```

The `core` config key was introduced in coverage.py 7.x alongside the environment variable support.

#### Result after applying the fix

```
TOTAL    1077    53    95%
Required test coverage of 85% reached. Total coverage: 95.08%
124 passed, 62 warnings in 358.04s
```

No `CoverageWarning` about unrecognised config keys → `core = "sysmon"` was accepted by coverage.py 7.14.0.

**Interview point 1**: `sys.monitoring` (PEP 669) is not just a coverage improvement — it is a general-purpose low-overhead event system for debuggers, profilers, and other tools. Setting granularity per-tool (instead of a global trace hook) reduces the overhead of multiple tools running simultaneously.

**Interview point 2**: The S5-6 attempt used `concurrency = ["asyncio", "thread"]`, but `asyncio` is not a valid `concurrency` value — that option only controls multi-threading/multi-processing scenarios. The correct axis for async coroutine coverage is the `core` backend, not `concurrency`.

---

### TD-014: cross-platform task runner

#### Why `Makefile` did not work on Windows

`make` is not bundled with Windows. It requires separate installation (`choco install make`, or WSL). The underlying `uv run ruff check .` / `uv run mypy app/` commands work fine on Windows — only the `make` wrapper was broken.

#### Why `poethepoet` over `just`

| Criterion | `Makefile` | `just` | `poethepoet` |
|-----------|-----------|--------|--------------|
| Windows out-of-the-box | ❌ | ✅ (separate binary) | ✅ |
| Requires separate install | ❌ (`make`) | ❌ (`winget install Casey.just`) | ✅ (`uv add --dev`) |
| `pyproject.toml` integration | ❌ | ❌ (separate `justfile`) | ✅ |
| Runs in project venv | ❌ (need `uv run` prefix in each recipe) | ❌ | ✅ |

`poethepoet` (`poe`) installs as a Python package (`uv add --dev poethepoet`), reads tasks from `[tool.poe.tasks]` in `pyproject.toml`, and executes them inside the project's virtual environment. No external tool installation is required beyond the project's own `uv sync`.

#### Configuration

```toml
[tool.poe.tasks]
lint     = "ruff check ."
format   = "ruff format ."
typecheck = "mypy app/"
check    = { sequence = ["format", "lint", "typecheck"] }
```

The `check` task uses a `sequence` table — `{ sequence = [...] }` is TOML inline-table syntax for a composite task that runs named tasks in order. If any task fails, execution stops.

#### Usage

```bash
uv run poe format      # ruff format .
uv run poe lint        # ruff check .
uv run poe typecheck   # mypy app/
uv run poe check       # format → lint → typecheck (all three)
```

`poe` commands work identically on Windows, Linux, and macOS.

**Interview point**: Having a standardised task runner in a project is primarily an **onboarding** and **consistency** tool. It documents the "inner loop" (lint, format, type-check, test) as runnable commands, removing the need for each developer to remember the full flag set. In CI, it also ensures the same commands are run locally and in the pipeline.

---

### Step C verification commands

**TD-013 — full test suite with coverage**:
```bash
uv run pytest --tb=short 2>&1 | tail -20
```

**TD-014 — all poe tasks**:
```bash
uv run poe check
```

---

### Step C — close TD-013 and TD-014

After verification, move TD-013 and TD-014 to Resolved in `docs/tech-debt.md`.

```bash
git add docs/tech-debt.md
git commit -m "docs(s8-3): close TD-013 and TD-014"
```

---

## Key Takeaways

### What did I learn?

I learned why async code is under-reported by coverage.py by default. The root cause is that
`sys.settrace` — Python's traditional trace hook — does not re-fire when a coroutine resumes
after an `await`. Python 3.12 introduced `sys.monitoring` (PEP 669) which fires at the bytecode
level, including on coroutine resume (`RESUME` opcode). Setting `core = "sysmon"` in
`[tool.coverage.run]` tells coverage.py 7.x to use this new backend, and it required only four
lines in `pyproject.toml` with no code changes at all.

I also learned how `poethepoet` integrates with `pyproject.toml` to provide cross-platform task
running. Tasks are defined as strings (single command) or `{ sequence = [...] }` (composite), and
invoked via `uv run poe <task>`. The project's virtual environment is automatically used — no
`uv run` prefix needed inside the task body.

### What would I do differently?

The S5-6 attempt to fix TD-013 used `concurrency = ["asyncio", "thread"]`, but that option
addresses multi-threading/multi-processing scenarios, not coroutine suspension. If I had
understood the `sys.settrace` vs `sys.monitoring` distinction earlier, I would have gone straight
to `core = "sysmon"` instead of trying `concurrency`. Next time I see a coverage gap in async
code, this is the first thing I would check.

### What surprised me?

I was surprised that `core = "sysmon"` in `pyproject.toml` worked with zero warnings the first
time. I expected there might be a version compatibility issue (it was added in coverage.py 7.x)
or that only the environment variable form (`COVERAGE_CORE=sysmon`) would be accepted. Having a
`pyproject.toml`-native config key for it is cleaner than setting an environment variable.

I was also surprised how little code was required for the whole goal: only config additions
and a file deletion. Both TD items closed with no production code changes.

### What is worth remembering for future goals?

1. **`[tool.coverage.run] core = "sysmon"`** — the one-line fix for async coverage
   under-reporting in Python 3.12+. Add this immediately when starting a project that uses async.

2. **`concurrency` vs `core` are different axes** — `concurrency` handles thread/greenlet/gevent
   scenarios; `core` selects the tracing backend. They solve different problems. Do not confuse
   them.

3. **`poethepoet` sequence task syntax** — `{ sequence = ["task1", "task2"] }` as a TOML
   inline table is the way to define a composite task. Each element references another named task,
   not a shell command.

4. **Tooling goals are small but high-leverage** — removing the Makefile and adding poe tasks
   reduced the onboarding friction for Windows developers to zero. Small configuration changes
   can have a disproportionately large impact on day-to-day workflow.
