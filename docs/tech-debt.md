# Technical Debt & Known Limitations

This file tracks outstanding technical debt, deferred decisions, and known limitations.
Items are added when a task is completed and something is intentionally left out of scope.

## Open Items

| ID | Sprint | Area | Description | Priority | Added |
|----|--------|------|-------------|----------|-------|
| TD-003 | S2-2 | pagination | `GET /transactions` returns all records without limit or cursor. | Low | S2-2 |
| TD-004 | S2-3 | idempotency | Current implementation returns `409 Conflict` on duplicate key. Stripe-style behaviour (return cached original response with `200 OK`) is not yet implemented. | Low | S2-3 |
| TD-005 | S2-3 | idempotency | Idempotency key is stored in Redis with a 24h TTL but the original response body is not cached. Cannot replay exact response on retry. | Low | S2-3 |
| TD-006 | S2-3 | observability | No structured logging or request tracing. Errors surface only in pytest output or container logs. | Medium | S2-3 |
| TD-007 | docs | docs | Numbering inconsistencies between `ARCHITECTURE.md` and `docs/adr/`: (1) ADR-001 name conflict — ARCHITECTURE.md calls it "Money as BIGINT" while docs/adr/001 is "Redis idempotency"; (2) ARCHITECTURE.md ADR-003 still describes Redis as "PostgreSQL UNIQUE constraint (MVP)" despite Redis being implemented in S2-3; (3) Section 6 lists Redis under "future additions" even though it is already in use. Fix: revise ARCHITECTURE.md and establish a numbering convention for docs/adr/. | Medium | S2-3 |
| TD-008 | S2-3 | architecture | Repository layer is not separated: services receive AsyncSession directly and call SQLAlchemy. No ADR or ARCHITECTURE.md entry — an implicit MVP-stage omission, not intentional design. Reduces unit-testability of the service layer and is a standard interview discussion point. Refactor candidate for S3+. | Medium | S2-3 |
| TD-009 | S2-3 | housekeeping | Root `/main.py` is a leftover from `uv init` (contains only `print("Hello from payment-ledger-api!")`). Dockerfile and conftest both reference `app/main.py`; the root file is unreferenced and safe to delete. Risk: new contributors may mistake it for the real entry point. | Low | S2-3 |
| TD-010 | S2-3 | housekeeping | `.gitignore` is sparse: `.pytest_cache/` was committed (exclusion missed); `.idea/` / `.vscode/` IDE directories are not excluded; general Python project patterns are incomplete. `.claude/` and `flagship-goal-prompt-template.md` were added today. Full cleanup recommended before portfolio publication. | Low | S2-3 |
| TD-011 | S2-X-2 | validation | `create_transaction` checks account existence but not `is_active` status. Posting to a deactivated account is currently allowed. Add `is_active=True` filter to the account existence query. | Medium | S2-X-2 |
| TD-013 | S3-7 | testing | coverage.py under-reports async function coverage. Lines after `await` in async functions (e.g. `deps.py` L39–44) are not recorded because `sys.settrace` trace hooks are not re-registered when a coroutine resumes after suspension. Actual execution is confirmed by test assertions (tests PASS with the expected status code). ~~Fix: add `[tool.coverage.run] concurrency = ["asyncio", "thread"]` to `pyproject.toml`~~ — tried in S5-6 (commit `b009592`) and reverted (commit `d9446d6`): `asyncio` is not a valid `concurrency` value (valid values are `thread`/`gevent`/`greenlet`/`eventlet`/`multiprocessing` only). Correct approach still unknown; `COVERAGE_CORE=sysmon` (Python 3.12 `sys.monitoring`) remains an untested candidate. Address before the S6 coverage 85%+ target is evaluated. | Low | S3-7 |
| TD-014 | S5-7 | tooling | `Makefile` (added in S5-6 for `make lint` / `make format` / `make typecheck` / `make check`) does not run on the developer's Windows host — `make` is not available without separate installation (e.g. via `choco`/`winget`/WSL). Discovered when `make typecheck` failed with "command not found" while verifying mypy strict locally. The underlying `uv run ...` commands work fine; only the `make` wrapper is unusable as-is. Fix: either document the raw `uv run` equivalents in README/CLAUDE.md for Windows users, or replace the Makefile with a cross-platform task runner (e.g. `uv run` scripts via `pyproject.toml` `[project.scripts]`, or `just`/`poethepoet`). | Low | S5-7 |

## Resolved

| ID | Description | Resolved in |
|----|-------------|-------------|
| TD-001 | `test_get_transactions_returns_list_shape` and `test_post_then_get_shows_persisted_record` were failing — `override_get_db` in conftest did not commit the session, unlike production `get_db`. Fixed by mirroring the try/commit/except/rollback pattern. | S2-4 |
| TD-002 | No authentication on any endpoint. All routes were open. | S3-4 |
| TD-012 | No currency scale management. Added `decimal_places` column to `Currency` model (JPY=0, EUR=2, USD=2). | S4-1 |

---

## How to Use This File

- **Add a row** when you intentionally leave something out of a Sprint Goal.
- **Move to Resolved** when the item is addressed in a later Sprint.
- **Priority**: `High` = blocks production readiness / `Medium` = degrades quality / `Low` = nice-to-have.
