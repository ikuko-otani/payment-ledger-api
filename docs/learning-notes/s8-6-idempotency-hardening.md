# S8-6: Idempotency Hardening — Request Fingerprint + redis.keys Removal

**Date**: 2026-06-21
**Goal**: Bind idempotency key to request body hash (TD-041) and replace `redis.keys()` with `scan_iter` (TD-042)
**Branch**: `feature/s8-6-idempotency-hardening`
**PR**: #87

## What changed

### TD-041: Request body fingerprint

The idempotency middleware (`app/dependencies/idempotency.py`) now computes a
SHA-256 hash of the raw request body and stores it in the Redis value alongside
the pending/response state. On replay, the stored fingerprint is compared with
the incoming request's fingerprint. A mismatch returns 422 Unprocessable Entity.

**Redis value structure (before):**
- New request: `"__pending__"` (plain string)
- Completed: `'{"id":"...","description":"...",...}'` (JSON response body)
- Detection: `json.loads()` success/failure

**Redis value structure (after):**
- New request: `'{"fingerprint":"sha256hex","status":"pending"}'`
- Completed: `'{"fingerprint":"sha256hex","response":{...}}'`
- Detection: `"response" in parsed` for completion; `fingerprint` comparison for body match

### TD-042: redis.keys() → scan_iter

`redis.keys("balance:{id}:*")` in the transaction write path was replaced with
`redis.scan_iter(match=pattern, count=100)`. `keys()` is O(N) over the entire
keyspace and blocks Redis (single-threaded); `scan_iter` uses cursor-based SCAN
which is O(1) per call.

**count=100 rationale**: The project's Redis keyspace is small (hundreds to low
thousands of keys). count=100 ensures the scan completes in 1-2 round trips
while keeping each SCAN call short enough to not block Redis.

## Key takeaways

- I learned how Stripe-style idempotency works at a deeper level. The naive
  implementation (key → response cache) is insufficient for financial systems
  because it silently drops requests when the same key is reused with a
  different payload. Adding a request fingerprint is a small change with
  outsized safety impact.

- I learned the difference between `Request.body()` in Starlette and PHP's
  `file_get_contents('php://input')`. Starlette caches the body after the
  first read in `self._body`, so reading it in a dependency does not interfere
  with FastAPI's Pydantic parsing downstream. This was initially a concern.

- I learned why `redis.keys()` is dangerous in production. It is O(N) over the
  entire keyspace and blocks the single-threaded Redis server until completion.
  `SCAN` (via `scan_iter`) is the recommended replacement — cursor-based,
  non-blocking, O(1) per call. The trade-off is that SCAN results are
  approximate (keys added/removed during iteration may be missed), but for
  cache invalidation this is acceptable because missed keys expire via TTL.

- The `count` parameter in SCAN is a hint, not a hard limit. It tells Redis
  how many hash table slots to examine per call, not how many keys to return.
  Choosing the right value depends on keyspace size and latency requirements.

- I was surprised how cleanly the data structure migration went. Changing from
  a two-format scheme (plain string vs JSON) to a unified JSON format
  simplified the detection logic — no more `json.loads()` try/except for
  format detection. The `"response" in parsed` check is more explicit.

- For future goals: the concurrent test pattern (`asyncio.gather` + sorted
  status code assertion) is reusable for any optimistic-locking scenario.
  The key insight is asserting on the *set* of outcomes, not their order.
