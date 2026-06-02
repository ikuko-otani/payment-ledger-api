# S5-1: structlog Setup + Request Logging Middleware

**Date**: 2026-06-02
**Goal**: Add structlog as a production dependency, implement a JSON processor chain,
and wire a `RequestLoggingMiddleware` via FastAPI's lifespan pattern so that every
request is logged without touching individual endpoints.

---

## Step C Walkthrough

### Step 1: Implement `configure_structlog()` processor chain (`app/core/logging.py`)

structlog's `configure()` accepts a list of **processor** functions that are applied in
order before each log event is emitted. The pipeline for this goal:

| Processor | Field added | Analogous to (Monolog) |
|---|---|---|
| `TimeStamper(fmt="iso")` | `"timestamp"` in ISO-8601 | `DateTimeProcessor` |
| `stdlib.add_log_level` | `"level"` | `IntrospectionProcessor` |
| `JSONRenderer()` | serialises everything to a JSON string | `JsonFormatter` |

`make_filtering_bound_logger(logging.INFO)` bakes an INFO-level filter into the logger
class itself, so DEBUG calls are dropped before any processor runs.

`cache_logger_on_first_use=True` freezes the processor chain after the first
`get_logger()` call for performance — useful to know when writing tests that need to
swap renderers.

```python
def configure_structlog() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.get_logger(__name__).info("structlog configured")
```

The final `log.info(...)` line satisfies the DONE condition "startup JSON log appears".

### Step 2: Implement `RequestLoggingMiddleware` (`app/middleware/logging.py`)

`BaseHTTPMiddleware.dispatch()` is the Starlette middleware hook. It receives a
`Request`, must call `await call_next(request)` to pass it down the chain, and must
return the `Response`. This mirrors PHP's `$next($request)` pattern in a PSR-15
middleware.

`time.perf_counter()` is a monotonic, high-resolution clock suitable for measuring
elapsed time within a single process (analogous to Oracle's `DBMS_UTILITY.GET_TIME`
but in nanoseconds).

structlog's calling convention: the first positional argument is the event name
(appears as `"event"` in the JSON); all keyword arguments become additional JSON fields.

```python
async def dispatch(self, request: Request, call_next: Callable) -> Response:
    start_time = time.perf_counter()
    response: Response = await call_next(request)
    process_time = time.perf_counter() - start_time
    logger.info(
        "request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        process_time=round(process_time, 4),
    )
    return response
```

### Step 3: Wire into `app/main.py` via lifespan

Modern FastAPI (0.95+) deprecates `@app.on_event("startup")` in favour of a
`lifespan` async context manager. The `yield` separates startup logic (before) from
shutdown logic (after).

`app.add_middleware()` must be called **before** `include_router()` — Starlette applies
middleware in reverse registration order (last registered = outermost wrapper).

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_structlog()
    yield

app = FastAPI(..., lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)
app.include_router(api_router)
```

### Errors encountered

**Typo 1 — `structlog.stblib` → `structlog.stdlib`**
Caught immediately by the Step 1 verification command (`uv run python -c ...`).
AttributeError message included "Did you mean: 'stdlib'?" which made it self-diagnosing.

**Typo 2 — `mothod` → `method`**
A keyword argument name typo in `logger.info()`. Appeared in the live log output as
`"mothod": "GET"` rather than `"method": "GET"`. Spotted during Step 4 curl verification.

**ruff I001 — import order in `app/main.py`**
`collections.abc` sorts before `contextlib` alphabetically; ruff's isort enforcer
(rule I001) caught this in CI. Fixed by reordering the two stdlib imports.

---

## Key Takeaways

**What did I learn?**

I learned structlog's **processor chain** model: rather than configuring a single
formatter, you compose a list of small transformation functions that each add or reshape
a field before the final renderer serialises the dict to a string. This makes it easy
to swap `JSONRenderer` for `ConsoleRenderer` in tests or development without touching
application code.

I also learned the modern FastAPI `lifespan` pattern as a replacement for the deprecated
`@app.on_event("startup")`. The `asynccontextmanager` approach is cleaner because
startup and shutdown logic live in the same function, and it integrates naturally with
dependency injection in tests.

**What would I do differently?**

I would run `uv run ruff check` locally before pushing, rather than discovering the
import order violation in CI. The rule is simple — stdlib imports are sorted
alphabetically — but easy to miss when writing by hand.

I would also slow down when typing keyword argument names in `logger.info()`. Both typos
(`stblib`, `mothod`) were purely typing errors that a local check or slower typing
would have caught before commit.

**What surprised me?**

I was surprised that `collections.abc` sorts before `contextlib` alphabetically
(c-o-l < c-o-n), which ruff enforces. I had assumed that any two stdlib imports in the
same block were acceptable in any order, but isort has strict alphabetical rules within
each import group.

I also found it notable that structlog keyword argument names become JSON field names
verbatim — there is no schema or validation between the call site and the output. This
is flexible but means typos in keyword names silently produce wrong field names in
production logs, which can break log-parsing pipelines.

**What is worth remembering for future goals?**

- structlog processor chain order: `TimeStamper → add_log_level → Renderer`. The
  renderer must be last; processors before it mutate the event dict in place.
- `lifespan` > `@app.on_event` for all new FastAPI startup/shutdown logic.
- `app.add_middleware()` before `app.include_router()` — Starlette wraps in reverse
  registration order.
- `BaseHTTPMiddleware` is convenient but has a known limitation with streaming
  responses; for S5+ goals involving SSE or large file downloads, consider a pure
  ASGI middleware instead.
- Always verify log field names in the actual Docker output, not just the Python
  invocation — typos in keyword arguments are silent.
