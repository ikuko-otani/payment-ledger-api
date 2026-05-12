# Technical Debt & Known Limitations

This file tracks outstanding technical debt, deferred decisions, and known limitations.
Items are added when a task is completed and something is intentionally left out of scope.

## Open Items

| ID | Sprint | Area | Description | Priority | Added |
|----|--------|------|-------------|----------|-------|
| TD-002 | S2 | auth | No authentication on any endpoint. All routes are open. | Medium | S2 |
| TD-003 | S2-2 | pagination | `GET /transactions` returns all records without limit or cursor. | Low | S2-2 |
| TD-004 | S2-3 | idempotency | Current implementation returns `409 Conflict` on duplicate key. Stripe-style behaviour (return cached original response with `200 OK`) is not yet implemented. | Low | S2-3 |
| TD-005 | S2-3 | idempotency | Idempotency key is stored in Redis with a 24h TTL but the original response body is not cached. Cannot replay exact response on retry. | Low | S2-3 |
| TD-006 | S2-3 | observability | No structured logging or request tracing. Errors surface only in pytest output or container logs. | Medium | S2-3 |
| TD-007 | docs | docs | ARCHITECTURE.md と docs/adr/ のナンバリング不整合: (1) ADR-001 の名称衝突（ARCHITECTURE.md は "Money as BIGINT"、docs/adr/001 は "Redis idempotency"）、(2) ARCHITECTURE.md ADR-003 が S2-3 実装済みの Redis を「PostgreSQL UNIQUE制約（MVP）」と記述したまま、(3) Section 6 が Redis を「将来追加したいもの」として列挙（実装済み）。対応: ARCHITECTURE.md 改訂 + docs/adr/ ナンバリングルール策定。 | Medium | S2-3 |
| TD-008 | S2-3 | architecture | Repository layer is not separated: services receive AsyncSession directly and call SQLAlchemy. No ADR or ARCHITECTURE.md entry — an implicit MVP-stage omission, not intentional design. Reduces unit-testability of the service layer and is a standard interview discussion point. Refactor candidate for S3+. | Medium | S2-3 |
| TD-009 | S2-3 | housekeeping | Root `/main.py` is a leftover from `uv init` (contains only `print("Hello from payment-ledger-api!")`). Dockerfile and conftest both reference `app/main.py`; the root file is unreferenced and safe to delete. Risk: new contributors may mistake it for the real entry point. | Low | S2-3 |
| TD-010 | S2-3 | housekeeping | `.gitignore` is sparse: `.pytest_cache/` was committed (exclusion missed); `.idea/` / `.vscode/` IDE directories are not excluded; general Python project patterns are incomplete. `.claude/` and `flagship-goal-prompt-template.md` were added today. Full cleanup recommended before portfolio publication. | Low | S2-3 |

## Resolved

| ID | Description | Resolved in |
|----|-------------|-------------|
| TD-001 | `test_get_transactions_returns_list_shape` and `test_post_then_get_shows_persisted_record` were failing — `override_get_db` in conftest did not commit the session, unlike production `get_db`. Fixed by mirroring the try/commit/except/rollback pattern. | S2-4 |

---

## How to Use This File

- **Add a row** when you intentionally leave something out of a Sprint Goal.
- **Move to Resolved** when the item is addressed in a later Sprint.
- **Priority**: `High` = blocks production readiness / `Medium` = degrades quality / `Low` = nice-to-have.
