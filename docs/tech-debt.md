# Technical Debt & Known Limitations

This file tracks outstanding technical debt, deferred decisions, and known limitations.
Items are added when a task is completed and something is intentionally left out of scope.

## Open Items

| ID | Sprint | Area | Description | Priority | Added |
|----|--------|------|-------------|----------|-------|
| TD-001 | S2-2 | tests | `test_get_transactions_returns_list_shape` and `test_post_then_get_shows_persisted_record` are skipped / failing — pending full `GET /transactions` implementation | Low | S2-2 |
| TD-002 | S2 | auth | No authentication on any endpoint. All routes are open. | Medium | S2 |
| TD-003 | S2-2 | pagination | `GET /transactions` returns all records without limit or cursor. | Low | S2-2 |
| TD-004 | S2-3 | idempotency | Current implementation returns `409 Conflict` on duplicate key. Stripe-style behaviour (return cached original response with `200 OK`) is not yet implemented. | Low | S2-3 |
| TD-005 | S2-3 | idempotency | Idempotency key is stored in Redis with a 24h TTL but the original response body is not cached. Cannot replay exact response on retry. | Low | S2-3 |
| TD-006 | S2-3 | observability | No structured logging or request tracing. Errors surface only in pytest output or container logs. | Medium | S2-3 |

## Resolved

| ID | Description | Resolved in |
|----|-------------|-------------|
| — | — | — |

---

## How to Use This File

- **Add a row** when you intentionally leave something out of a Sprint Goal.
- **Move to Resolved** when the item is addressed in a later Sprint.
- **Priority**: `High` = blocks production readiness / `Medium` = degrades quality / `Low` = nice-to-have.
