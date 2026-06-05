# S5-5: Redis Balance Cache — Learning Notes

**Goal**: Add Cache-Aside caching to `GET /accounts/{id}/balance` using Redis.
**Branch**: `feature/s5-5-redis-balance-cache`
**Date**: 2026-06-05

---

## Step C Walkthrough

See scaffold and implementation in:
- `app/core/cache.py` — `get_redis_client()` dependency
- `app/api/v1/routes/accounts.py` — Cache-Aside logic
- `app/api/v1/routes/transactions.py` — cache invalidation on POST
- `tests/test_balance_cache.py` — hit / miss / invalidation tests

---

## Q: Why store balance in Redis cache rather than a DB table?

Redis cache is used for **read speed**, not as a source of truth.

| Approach | Description |
|---|---|
| Redis cache (this project) | Temporary copy of a computed value. Deleted on write, rebuilt on next read. DB remains the source of truth. |
| DB balance snapshot table | Precomputed balance stored in a separate DB table alongside journal entries. Requires schema changes and write-path consistency guarantees. |

Redis avoids schema changes and keeps consistency simple: when a transaction is posted, the cache key is deleted. The next GET recomputes from DB and repopulates the cache.

---

## Q: Is the "nightly batch to update balance tables" pattern in core banking systems outdated?

Not obsolete — but the reason for using it has shifted.

### Why it persists in traditional banking

- **Regulatory requirements**: Basel III and similar regulations mandate end-of-day (EOD) balance reporting. A nightly batch produces the authoritative daily snapshot used for audit and compliance.
- **Historical constraints**: Mainframe + COBOL systems couldn't aggregate in real time. Nightly batch was the practical solution.
- **Audit trail**: A committed EOD balance row is easier to certify than a dynamically computed value.

### What modern fintech does instead (CQRS + event-driven)

Fintechs like Mollie, Revolut, and Stripe use **CQRS (Command Query Responsibility Segregation)**:

```
Write model  →  journal entry INSERT  →  event published
                                               ↓
Read model   ←  balance view updated  ←  event consumed (real-time)
```

The read model (balance) is updated the moment a transaction is confirmed — no overnight wait. This also maps naturally to event sourcing, where every transaction is an immutable event and the balance is always derivable from the event log.

### Relationship to this project

This project's design (compute balance from journal entries on demand, cache the result) is conceptually aligned with the CQRS starting point: the write model (entries table) is the source of truth, and the Redis cache is the read optimization layer.

**For EU fintech roles (Mollie, Revolut, etc.)**: being able to explain both the legacy batch approach and the modern event-driven alternative — and articulate *why* each exists — is a strong signal in system design interviews.

---

## Related

- ADR: `docs/adr/001-redis-for-idempotency-key.md`
- Cache invalidation implementation: `app/api/v1/routes/transactions.py`
- Cache-Aside pattern: `app/api/v1/routes/accounts.py`
