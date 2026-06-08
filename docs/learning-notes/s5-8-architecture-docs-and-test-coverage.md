# S5-8: ARCHITECTURE.md Design Docs + S5 Test Coverage Completion

**Date**: 2026-06-09
**Branch**: `feature/s5-8-architecture-docs-and-test-coverage`
**Goal**: Elevate the S5 implementation into portfolio material by documenting
design decisions in `ARCHITECTURE.md` in English and filling in test coverage
gaps left by earlier S5 sprints.

---

## Step C Walkthrough

### 1. ARCHITECTURE.md — Section 9 (three subsections)

Added `## 9. Observability & Caching Design (S5)` to `ARCHITECTURE.md` in
ADR format (Decision / What was rejected / Rationale / Trade-off).

**9.1 Why async SQLAlchemy over sync**

- *Decision*: SQLAlchemy 2.0 async engine + asyncpg + `AsyncSession` end-to-end.
- *What was rejected*: sync SQLAlchemy relying on FastAPI's `run_in_threadpool`.
- *Core rationale*: Consistency with FastAPI's ASGI event loop. While one request
  `await`s a DB query, the event loop can advance other requests — no thread-per-request
  cost (contrasts with PHP-FPM's one-process-per-request model).
- *Trade-off*: `await` discipline required everywhere; `MissingGreenlet` errors if
  lazy-load is accessed outside an awaited context; narrower async extension ecosystem.

**9.2 Observability stack (structlog + OTel + Jaeger)**

- *Decision*: structlog for JSON-structured logs, OpenTelemetry for tracing
  instrumentation, Jaeger as the trace backend. `trace_id` is bound into every
  structlog entry via `structlog.contextvars` so logs and traces can be
  correlated in either direction.
- *What was rejected*: plain stdlib `logging` (unstructured), tracing-only,
  logs-only.
- *Core rationale*: "Logs answer *what* happened; traces answer *where* the time
  went." Binding `trace_id` into structlog allows pivoting from a slow Jaeger
  trace directly to its structured log lines and vice versa.
- *Trade-off*: Three moving parts, subtle misconfiguration failure mode —
  instrumenting OTel at the wrong lifecycle stage produces
  `trace_id = "000...000"` silently (encountered in S5-3; documented in
  `docs/learning-notes/s5-3-otel-fastapi-instrumentation.md`). Metrics pillar
  (Prometheus) is not yet implemented.

**9.3 Caching strategy (Cache-Aside for account balances)**

- *Decision*: Cache-Aside pattern for `GET /accounts/{id}/balance`.
  Key: `balance:{account_id}:{as_of_date}`. Explicit invalidation on every
  transaction write (cache keys for all affected accounts are deleted).
- *What was rejected*: Write-through (couples write path to cache availability);
  TTL-only invalidation (staleness window unacceptable for a financial ledger).
- *Core rationale*: Balance changes if and only if a transaction posts to the
  account — a precisely identifiable event. Explicit invalidation keeps the
  cache always-correct. Cache-Aside degrades gracefully: if Redis is down, the
  API still serves correct results from PostgreSQL.
- *Trade-off*: Invalidation must enumerate every affected `as_of` cache key
  ("cache invalidation is one of the two hard problems in computer science").
  Cache stampede risk accepted at MVP scale.

---

### 2. Test coverage completion

#### Finding 1 — OTel TracerProvider was never configured in the test session

`async_client` in `tests/conftest.py` wraps `httpx.ASGITransport` directly,
which does not trigger FastAPI's ASGI lifespan events. Therefore
`configure_telemetry()` (called inside `lifespan`) never ran, leaving the global
`TracerProvider` as OTel's default no-op. As a result, every span created by
`FastAPIInstrumentor` was an `INVALID_SPAN` with `trace_id = 0`, and
`RequestLoggingMiddleware` was binding `"00000000000000000000000000000000"` into
every structlog entry across the entire test suite — silently, because the
existing test only checked `"trace_id" in request_log` (key presence), not the
value.

**Fix**: added a session-scoped, autouse `_configure_test_tracer_provider`
fixture to `conftest.py`. It calls `trace.set_tracer_provider()` once with a
`TracerProvider` backed by `InMemorySpanExporter`, making real non-zero trace
IDs available without a live Jaeger/OTLP endpoint.

`trace.set_tracer_provider()` may only be called once per process (subsequent
calls are silently ignored after logging a warning) — hence the `scope="session"`
requirement. A function-scoped fixture would silently stop working after the
first test.

**New test** (`tests/test_middleware_logging.py`):

```
test_request_log_trace_id_is_valid_otel_span_not_zero
```

Asserts that the captured `trace_id` is not `"0" * 32` and has length 32.
Acts as a regression guard for the S5-3 `trace_id = 0` bug: if OTel
instrumentation breaks again, this test fails before any human notices the
silent placeholder appearing in production logs.

---

#### Finding 2 — S5 wiring functions were never exercised by the test suite

`configure_structlog()`, `configure_telemetry()`, and `get_redis_client()`
had 56–67% coverage because all three run exclusively inside the FastAPI
lifespan or are replaced by `dependency_overrides` — neither of which is
triggered by the `ASGITransport`-based test client.

**Approach — "meaningful 80%" vs "formal 80%"**

These are *wiring* functions whose job is "call library X with arguments Y."
The meaningful thing to verify is "were the right arguments passed and is
cleanup wired up?" — not "does the library work?" (that is the library's own
test suite's responsibility). Mock-based unit tests are therefore the correct
tool here, whereas the rest of this test suite uses integration-style tests
against real containers.

This is the first use of `unittest.mock` in the test suite. The guiding
principle: use mocks for *configuration/wiring code*; use real containers for
*end-to-end behavior*.

**New file**: `tests/test_observability_config.py`

| Test | What it verifies |
|---|---|
| `test_configure_structlog_wires_json_renderer_and_print_logger` | After calling `configure_structlog()`, `structlog.get_config()` reflects `JSONRenderer`, `TimeStamper`, and `PrintLoggerFactory`. Torn down with `structlog.reset_defaults()` to avoid polluting subsequent tests. |
| `test_configure_telemetry_builds_provider_tagged_with_service_name` | Mocks `trace.set_tracer_provider` to inspect the `TracerProvider` that `configure_telemetry()` constructs. Asserts `resource.attributes[SERVICE_NAME] == "payment-ledger-api"` — the tag that makes this service's traces identifiable in Jaeger. Mocking also sidesteps the "only callable once" constraint. |
| `test_get_redis_client_builds_from_settings_and_closes_on_exit` | Mocks `aioredis.from_url` and verifies it is called with `settings.redis_url` and `decode_responses=True` (critical: without this flag the service layer receives bytes instead of strings). Also asserts `client.aclose()` is awaited when the generator exits — confirming no resource leak. |

**Result**: all S5 new-code modules at 100%; overall coverage 90%
(91 tests, all green).

---

### 3. S5 final DONE-condition check (Step 6 findings)

| Condition | Result |
|---|---|
| JSON structured logs (trace_id / request_id / latency_ms) | ✅ test green |
| Jaeger UI trace display | ✅ confirmed manually |
| balance cache hit < 10ms | ✅ Redis round-trip avg 0.93ms (`redis-cli --latency`) |
| mypy strict zero errors | ✅ `no issues found in 51 source files` |
| ruff zero errors | ✅ `All checks passed!` |

**Note on the < 10ms target**: curl `time_total` for a cache-hit request was
~99ms end-to-end. Isolating layers showed Redis itself responds in < 1ms
(avg 0.93ms); the remaining ~98ms is HTTP/auth/serialization overhead —
primarily `get_current_user` re-querying the `users` table on every
authenticated request (registered as TD-015).

---

## Files Changed

| File | Change |
|---|---|
| `ARCHITECTURE.md` | Section 9 added — three ADR-style sections in English |
| `tests/conftest.py` | `_configure_test_tracer_provider` session-scoped autouse fixture |
| `tests/test_middleware_logging.py` | `test_request_log_trace_id_is_valid_otel_span_not_zero` added |
| `tests/test_observability_config.py` | New file — unit tests for S5 wiring functions |
| `docs/tech-debt.md` | TD-015 registered |

---

## Key Takeaways

_(To be added in Step D after the PR is merged.)_
