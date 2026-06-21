# S8-9: Balance cache-hit DB-free optimization

**Date**: 2026-06-21
**Goal**: TD-046 — eliminate DB query on cache-hit path for `GET /accounts/{id}/balance`
**PR**: #90

---

## Key takeaways

### What did I learn?

I learned that a seemingly small fix (adding `find_by_id` for currency in TD-038)
can silently regress a performance optimization (TD-015's zero-DB cache hit).
The fix was correct in isolation — it added currency and 404 handling — but it
introduced a DB round-trip on every request, including cache hits.

The solution was to co-locate related data in the cache value.  Changing from
`str(balance)` to `json.dumps({"balance": ..., "currency": ...})` restored
the DB-free hot path while keeping currency available on cache hit.

I also learned that SQLAlchemy's `func.sum()` on a `BIGINT` column returns
Python `Decimal`, not `int`, even when the column type annotation says `int`.
This caused a `json.dumps` serialization failure that was not caught by mypy
because the type annotation on `calculate_balance` says `-> int`.

### What would I do differently?

When adding a field to a cached response (like `currency` in TD-038), I would
immediately consider whether the new data should be embedded in the cache value
rather than fetched separately.  The question to ask is: "Does this new field
require a DB query on the cache-hit path?"  If yes, co-locate it in the cache.

### What surprised me?

The `Decimal` serialization error surprised me.  PostgreSQL's `SUM(bigint)`
returns `numeric`, which SQLAlchemy maps to Python `Decimal`.  The repository
method's `-> int` return type annotation did not enforce an actual `int` at
runtime — it is purely a static-analysis hint.  The fix was a simple
`int(balance)` cast before `json.dumps`.

### What is worth remembering for future goals?

- **Cache value design**: when caching a response, include all fields needed
  to reconstruct the response without any DB access.  This is the "cache-aside
  completeness" principle.
- **Domain invariant as optimization justification**: a non-existent account
  can never have cached balance entries, so 404 handling is only needed on
  cache miss.  This kind of reasoning should be documented (in code comments
  or ADRs) so future developers don't re-add the guard "just in case."
- **Test pattern for DB-free verification**: using a non-existent account ID
  with a pre-populated cache entry is a clean way to prove the cache-hit path
  does not touch the DB — if it did, `find_by_id` would return `None` and the
  route would 404.
- **SQLAlchemy aggregate return types**: always assume `func.sum()` and
  `func.coalesce()` return `Decimal`, regardless of the column type.  Cast
  explicitly when serializing.
