# S5-2: Request Log Fields — trace_id / request_id / latency_ms / status_code

**Date**: 2026-06-03
**Goal**: Extend `RequestLoggingMiddleware` with structured log fields required for
production fintech observability: `request_id`, `trace_id`, `latency_ms`, and the
`X-Request-ID` response header. Use `structlog.contextvars` to propagate `request_id`
to all log lines within the same request.

---

## Step C Walkthrough

### Step 1: Add `merge_contextvars` to the processor chain (`app/core/logging.py`)

`structlog.contextvars.merge_contextvars` is a processor that reads whatever has been
bound via `bind_contextvars()` and **merges it into the event dict** before subsequent
processors run. Without it in the chain, context-bound values are never reflected in
the log output.

It must be placed **first** in the chain so that all subsequent processors (TimeStamper,
add_log_level, JSONRenderer) see the merged fields:

```python
processors=[
    structlog.contextvars.merge_contextvars,  # must be first
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.stdlib.add_log_level,
    structlog.processors.JSONRenderer(),
],
```

### Step 2: Extend `dispatch()` in `RequestLoggingMiddleware` (`app/middleware/logging.py`)

#### Why `contextvars` is async-safe

Python's `contextvars.ContextVar` (introduced in 3.7) gives each asyncio **task** its
own isolated copy of context. When a new task is created, it gets a **copy** of the
parent's context — changes do not propagate back. This is fundamentally different from
`threading.local`, which is shared across all coroutines on the same thread.

`structlog.contextvars.bind_contextvars()` stores values in `ContextVar`, so binding
`request_id` for task A is invisible to the concurrently running task B.

#### Why `clear_contextvars()` belongs at the top of `dispatch()`

`BaseHTTPMiddleware` creates a new `dispatch()` invocation per request, but the asyncio
context is **inherited from the parent task** (the server worker). Without clearing,
values from a previous request can leak into the current one — especially visible in
tests where requests run sequentially on the same event loop.

#### X-Request-ID flow

```
Incoming request
  has X-Request-ID header? ──yes──► use that value as request_id
                           ──no───► generate str(uuid.uuid4())
         │
         ▼
  bind_contextvars(request_id=..., trace_id=...)
  call_next(request)               ← all log lines inside here inherit request_id
         │
         ▼
  response.headers["X-Request-ID"] = request_id  ← echo back to client
  logger.info("request", method=..., latency_ms=...)
```

#### `latency_ms` unit

`time.perf_counter()` returns seconds as a float. Multiplying by 1000 converts to
milliseconds. `round(..., 2)` gives two decimal places (e.g., `433.9`).

```python
async def dispatch(self, request: Request, call_next: Callable) -> Response:
    structlog.contextvars.clear_contextvars()

    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    trace_id = str(uuid.uuid4())  # stub: replaced by OTel context in S5-3

    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        trace_id=trace_id,
    )

    start_time = time.perf_counter()
    response: Response = await call_next(request)
    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    response.headers["X-Request-ID"] = request_id

    logger.info(
        "request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_ms=latency_ms,
    )
    return response
```

### Step 3: Test the middleware (`tests/test_middleware_logging.py`)

#### Why `capture_logs()` alone is not enough

`structlog.testing.capture_logs()` temporarily replaces **all** processors with a single
`LogCapture`. Because `merge_contextvars` is no longer in the chain, values bound via
`bind_contextvars()` are never merged into the captured event dict — so `request_id`
and `trace_id` would be missing from assertions.

Fix: configure structlog manually with a two-processor chain before making the request:

```
[merge_contextvars, LogCapture()]
```

The `try / finally` pattern ensures the original processor chain is always restored,
even if an assertion inside `try` raises an exception:

```python
cap = structlog.testing.LogCapture()
old_processors = structlog.get_config()["processors"]
structlog.configure(processors=[structlog.contextvars.merge_contextvars, cap])
try:
    response = await async_client.get("/api/v1/accounts")
finally:
    structlog.configure(processors=old_processors)
```

### Errors encountered

**Typo — `structlog.contextvars.clear.clear_contextvars()`**
An extra `.clear` segment was typed between `contextvars` and `clear_contextvars()`.
At runtime the middleware raised `AttributeError: module 'structlog.contextvars' has no
attribute 'clear'`, which caused `dispatch()` to abort before `call_next()` was reached.
Effect: all requests returned 500, no request log was emitted, and the `X-Request-ID`
header was absent. Diagnosed by the absence of log output after the startup line and
the empty `X-Request-ID` grep result.

---

## Key Takeaways

**What did I learn?**

I learned how `structlog.contextvars` propagates values across all log calls within a
single async task. The key insight is that `bind_contextvars()` writes to a `ContextVar`,
and `merge_contextvars` (as a processor) reads those values into the event dict at log
time. Without the processor in the chain, the binding is invisible in the output.

I also learned why `clear_contextvars()` must be called at the start of each request
dispatch: asyncio tasks inherit their parent's context, so without an explicit clear,
a previous request's `request_id` can leak into the current one.

Finally, I learned that `capture_logs()` in tests replaces the entire processor chain,
which silently drops `merge_contextvars`. The fix is to include `merge_contextvars`
explicitly in the temporary test chain.

**What would I do differently?**

I would read the function signature more carefully before typing. The typo
`structlog.contextvars.clear.clear_contextvars()` was a pure typing error — slowing
down at unfamiliar API names and verifying with a quick search would have prevented it.

I would also add a smoke test (one `curl` to check for a 200 or expected JSON) earlier
in the implementation, before the full `docker compose logs` verification, to catch
middleware-level errors immediately.

**What surprised me?**

I was surprised that `capture_logs()` silently drops context-bound fields rather than
raising an error or warning. If I had only asserted on explicitly-passed fields
(`method`, `path`, etc.) and skipped `request_id`/`trace_id`, the test would have
passed while missing the most important part of the DONE condition.

**What is worth remembering for future goals?**

- `merge_contextvars` must be **first** in the processor chain; it must also be included
  explicitly when temporarily reconfiguring structlog for tests.
- `clear_contextvars()` at the top of `dispatch()` is a defensive necessity, not
  optional — asyncio context inheritance makes previous bindings visible without it.
- `trace_id` is a UUID4 stub here; S5-3 will replace it with the actual OpenTelemetry
  trace context. The field name and position in the log are already production-ready.
- `X-Request-ID` echoed in the response header lets clients correlate their own logs
  with server logs — standard practice in Mollie/Revolut-style fintech APIs.
- `latency_ms = round((perf_counter() - start) * 1000, 2)` is the canonical pattern
  for millisecond-precision elapsed time in Python.
