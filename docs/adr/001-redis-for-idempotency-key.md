# ADR-001: Use Redis for Idempotency Key Storage

## Status

Accepted

## Context

`POST /transactions` creates financial records that must not be duplicated if a client
retries due to a network error. We need a mechanism to detect and reject duplicate
requests identified by a client-supplied `Idempotency-Key` header.

Two candidate storage backends were considered:

1. **PostgreSQL** — add an `idempotency_keys` table, insert the key before writing the
   transaction, and rely on a `UNIQUE` constraint to detect duplicates.
2. **Redis** — store the key as a string with a TTL and check existence before
   processing the request.

## Decision

Store idempotency keys in **Redis** with `TTL = 86400 seconds (24 hours)`.

The check is implemented as a FastAPI `Depends` function in
`app/dependencies/idempotency.py` and injected into the `POST /transactions` route.

## Rationale

| Factor | PostgreSQL | Redis |
|--------|-----------|-------|
| TTL management | Manual (`created_at` + cron job) | Built-in `EX` option |
| Schema change required | Yes (new table + migration) | No |
| Read latency for hot path | ~1–5 ms (indexed SELECT) | < 1 ms (in-memory) |
| Persistence on restart | Yes | No (keys lost — acceptable for 24h window) |
| Operational complexity | Low (already running) | Medium (new service dependency) |

The 24-hour TTL aligns with common industry practice (Stripe uses 24h).
Financial clients are expected to retry within this window; older duplicates are
considered stale and a new transaction would be legitimate.

## Current Behaviour vs. Stripe-Style

This implementation returns `409 Conflict` when a duplicate key is detected.
Stripe's API returns `200 OK` with the **original response body** on a duplicate.

The Stripe-style behaviour requires caching the serialised response alongside the key,
which adds complexity. This is tracked as **TD-004 / TD-005** in `docs/tech-debt.md`
and is deferred to a future iteration.

## Consequences

- Redis is now a **required runtime dependency** (added to `compose.yaml`).
- Tests that cover idempotency use `testcontainers` to spin up a real Redis instance,
  keeping the test suite self-contained.
- If Redis is unavailable at startup, the application will fail to connect.
  No circuit-breaker or fallback is implemented yet (see TD-006).

## References

- [Stripe Idempotency Keys](https://stripe.com/docs/api/idempotent_requests)
- [IETF draft-ietf-httpapi-idempotency-key-header](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/)
- Implementation: `app/dependencies/idempotency.py`
- Related tech debt: `docs/tech-debt.md` TD-004, TD-005
