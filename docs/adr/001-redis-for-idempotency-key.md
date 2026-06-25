# ADR-001: Use Redis for Idempotency Key Storage

## Status

Accepted — evolved to Stripe-style response replay (see below)

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

The check is implemented as a FastAPI `Depends` generator in
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

## Implementation: Two-Phase State Machine with Response Replay

The initial implementation returned `409 Conflict` for all duplicate keys (TD-004).
This was later evolved to a Stripe-style two-phase state machine with request
fingerprinting and response replay (TD-004, TD-005, TD-041 — all resolved).

The current behaviour:

1. **New request** — `SET NX` stores a JSON payload containing a SHA-256 fingerprint
   of the request body and `"status": "pending"`, with a 24-hour TTL.
2. **On success** — the pending marker is overwritten with the serialised response
   body, so future duplicate requests replay the cached response with `200 OK`.
3. **In-flight duplicate** — if the same key arrives while the first request is still
   processing (`status: "pending"`), the API returns `409 Conflict`.
4. **Fingerprint mismatch** — if the same key is reused with a different request body,
   the API returns `422 Unprocessable Entity`, preventing silent request substitution.
5. **On failure** — the key is deleted from Redis, allowing the client to retry with
   the same key.

This design guarantees exactly-once semantics for successful requests and safe retry
for failed ones. The trade-off is increased per-key storage in Redis (response body
cached alongside the fingerprint) and slightly more complex error-handling logic.

## Consequences

- Redis is a **required runtime dependency** on the write path (added to
  `compose.yaml`). If Redis is unavailable, `POST /transactions` returns `500`
  rather than silently skipping the idempotency check — correctness over availability,
  because a skipped check could create duplicate transactions.
- Tests that cover idempotency use `testcontainers` to spin up a real Redis instance,
  keeping the test suite self-contained.

## References

- [Stripe Idempotency Keys](https://stripe.com/docs/api/idempotent_requests)
- [IETF draft-ietf-httpapi-idempotency-key-header](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/)
- Implementation: `app/dependencies/idempotency.py`
- Resolved tech debt: TD-004 (response replay), TD-005 (response caching),
  TD-041 (request fingerprinting) — see `docs/tech-debt.md`
