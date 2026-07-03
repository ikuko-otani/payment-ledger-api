# Technical Debt & Known Limitations

This file tracks outstanding technical debt, deferred decisions, and known limitations.

## Open Items

| ID | Area | Description | Priority |
|----|------|-------------|----------|
| TD-047 | Ledger design | Adopt event sourcing (Outbox pattern) for the transaction lifecycle — the current `POSTED → VOIDED` status machine works, but an append-only event log would capture every state transition for compliance replay and debugging. | Medium |
| TD-048 | CI | Include a baseline load test in CI — Locust results are currently static snapshots in `docs/loadtest/`; running on every PR would catch performance regressions before merge. | Low |
| TD-049 | Auth | Use short-lived JWTs (5 min) with a refresh endpoint — the current 30-minute token lifetime (see [ADR-006](adr/006-jwt-claims-no-db-per-request.md)) trades latency for a wide revocation window; a refresh flow would tighten it without reintroducing per-request DB lookups. | Medium |
| TD-050 | Multi-currency | Per-entry `ROUND_HALF_UP` conversion to USD does not guarantee USD balance across a transaction. When N debit entries are converted individually, `SUM(convert(debit_i))` may differ from `convert(SUM(debit_i))` by up to N USD cents. The original-currency balance is always enforced; only the `converted_amount_usd` view is affected. Mitigation options: (a) residual entry — absorb rounding difference into one designated entry; (b) rounding difference G/L account — auto-post discrepancy to a dedicated account; (c) transaction-level aggregate conversion — store one USD total per transaction rather than per entry. Documented by `test_fx_rounding_error_bounded_by_entry_count` in `tests/test_balance_invariant_hypothesis.py`. See also ARCHITECTURE.md §7. **Note**: a USD balance check cannot be added independently of the rounding fix — doing so would reject legitimate original-currency-balanced transactions where per-entry rounding produces a USD imbalance; the check and the rounding fix must be implemented together. **Scope note**: for this system (management accounting ledger where original-currency balance is the primary correctness requirement and USD is a reference/reporting currency only), this limitation is acceptable. A stricter requirement would arise if USD were used as a settlement or consolidated reporting currency across legal entities — the scenario where global ERP systems (SAP, Oracle) enforce unified-currency balance. | Low |

## Resolved

Items are compressed to one-line summaries. Each row describes the problem, fix, and observable effect.

### Security & Auth

| ID | Summary |
|----|---------|
| TD-002 | No authentication → JWT auth + RBAC added to all endpoints |
| TD-023 | `python-jose` had CVE in transitive `ecdsa` dependency → migrated to PyJWT |
| TD-032 | CI failing from dependency CVEs (cryptography, starlette, python-multipart) → upgraded all |

### Data Integrity

| ID | Summary |
|----|---------|
| TD-016 | `Entry.amount` was 32-bit `Integer` → changed to `BigInteger` |
| TD-024 | Entry currency not validated against account currency → cross-check added, mismatch returns 422 |
| TD-035 | `accounts.currency` and `entries.currency` had no FK → `ForeignKey("currencies.code")` added |
| TD-012 | No currency scale management → `decimal_places` column added to `Currency` model |
| TD-039 | Exchange rate required exact date match → changed to most recent rate on-or-before |
| TD-051 | `calculate_balance` excluded VOIDED transactions while including their sign-flipped reversal, so voiding netted to `-original` instead of `0` → filter widened to `status IN (POSTED, VOIDED)`; `test_balance_after_void_nets_to_zero` added as regression guard |

### Idempotency

| ID | Summary |
|----|---------|
| TD-004 | Duplicate idempotency key returned 409 → Stripe-style 200 replay with cached response |
| TD-005 | Response body not cached alongside key → `IdempotencyContext.cache()` added |
| TD-017 | Key confirmed before DB commit; failed requests blocked retries for 24h → cleanup on failure via generator dependency |
| TD-041 | Key not bound to request body → SHA-256 fingerprint comparison, mismatch returns 422 |
| TD-045 | No concurrent in-flight test → added `test_concurrent_inflight_idempotency_returns_409` |

### Performance & Scalability

| ID | Summary |
|----|---------|
| TD-026 | Default `pool_size=5` caused `QueuePool limit of size 5 overflow 10 reached` under 100 concurrent users → configurable `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` env vars; post-fix error rate 0% |
| TD-027 | Synchronous bcrypt blocked the event loop → wrapped in `asyncio.to_thread` |
| TD-020 | Redis connection pool created per request → singleton lifespan client, ~48% latency improvement |
| TD-015 | Balance endpoint ~65ms on cache hit due to per-request DB query → JWT claims eliminated DB lookup, ~37ms |
| TD-046 | Balance cache hit re-introduced DB query for currency → cached currency alongside balance in Redis JSON |
| TD-030 | Currency conversion queries scaled O(N) per entry → resolve rate once per transaction |
| TD-042 | `redis.keys()` O(N) keyspace scan for cache invalidation → cursor-based `scan_iter` |
| TD-028 | Dockerfile used dev server → multi-worker `uvicorn` (4 workers) for production |
| TD-029 | Hardcoded pool settings → env-configurable, total connections bounded within `max_connections` |
| TD-052 | Balance cache used the same short TTL for closed historical dates as for today, forcing redundant recomputation of values that invalidation-on-write already keeps correct → longer `balance_cache_ttl_historical_seconds` applied when `as_of` is in the past |

### API Correctness

| ID | Summary |
|----|---------|
| TD-003 | `GET /transactions` had no pagination → `limit`/`offset` added |
| TD-040 | `/accounts`, `/currencies`, `/exchange-rates` returned unbounded result sets → pagination added |
| TD-025 | List queries had no `ORDER BY` → deterministic ordering added (pagination correctness) |
| TD-033 | Currencies list non-deterministic order → `ORDER BY code` added |
| TD-034 | Exchange rates list non-deterministic order → `ORDER BY effective_date DESC` added |
| TD-011 | `create_transaction` didn't check `is_active` → inactive accounts now return 422 |
| TD-038 | `BalanceResponse` missing currency code → `currency` field added |
| TD-018 | Balance cache invalidation ran before commit → explicit commit before cache delete |
| TD-031 | TOCTOU race on user email uniqueness → `IntegrityError` catch added, tested with `asyncio.gather` |

### Architecture & Code Quality

| ID | Summary |
|----|---------|
| TD-008 | No repository layer separation → 6 repository abstractions extracted under `app/repositories/` |
| TD-019 | Services raised `HTTPException` directly → domain exception hierarchy (`DomainError` / `ValidationError` / `ConflictError`) |
| TD-022 | Route handlers embedded ORM queries → extracted to service layer |
| TD-036 | Dead `balance.py` service code → deleted after repository migration |
| TD-037 | Dead `ledger_service.py` code → deleted after repository migration |
| TD-021 | Admin mutations missing audit log entries → audit rows added for currencies, exchange rates, users |

### Observability & Tooling

| ID | Summary |
|----|---------|
| TD-006 | No structured logging or request tracing → structlog + OpenTelemetry + Jaeger |
| TD-013 | coverage.py under-reported async lines → `sys.monitoring` backend enabled (Python 3.12+) |
| TD-014 | `Makefile` not cross-platform → replaced with `poethepoet` tasks |
| TD-010 | `.gitignore` incomplete → Python standard patterns added |
| TD-007 | `ARCHITECTURE.md` had stale content and numbering conflicts → updated |
| TD-043 | Japanese comments in core files → translated to English |
| TD-044 | Japanese comment in `alembic/env.py` → translated to English |

### Test Infrastructure

| ID | Summary |
|----|---------|
| TD-001 | Test fixture session didn't commit → mirrored production `try/commit/except/rollback` pattern |
| TD-009 | Root `main.py` leftover from `uv init` → confirmed absent, no action needed |

---

## How to Use This File

- **Add a row** to Open Items when you intentionally leave something out of scope.
- **Move to Resolved** when the item is addressed.
- **Priority**: `High` = blocks production readiness / `Medium` = degrades quality / `Low` = nice-to-have.
