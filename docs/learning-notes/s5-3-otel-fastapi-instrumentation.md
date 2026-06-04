# S5-3: OpenTelemetry SDK + FastAPI Instrumentation

**Date**: 2026-06-04
**Branch**: feature/s5-3-otel-fastapi-instrumentation
**PR**: #35

---

## Step C Walkthrough

### What was built

| File | Change |
|------|--------|
| `app/core/telemetry.py` | New — `configure_telemetry()`: TracerProvider + BatchSpanProcessor + OTLPSpanExporter |
| `app/main.py` | Added OTel initialization to lifespan; `FastAPIInstrumentor().instrument_app(app)` at module level |
| `app/middleware/logging.py` | Replaced stub `trace_id = str(uuid.uuid4())` with OTel span context |
| `.env` | Added `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317` |

Dependencies added: `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`,
`opentelemetry-instrumentation-sqlalchemy`, `opentelemetry-exporter-otlp-proto-grpc`

---

### Key implementation details

#### `configure_telemetry()` structure

```python
resource = Resource.create({SERVICE_NAME: "payment-ledger-api"})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter(endpoint=endpoint)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)
```

`BatchSpanProcessor` queues spans and exports asynchronously — export failures
(e.g. Jaeger unavailable) do not block request processing.

#### `FastAPIInstrumentor` must be at module level

Calling `instrument_app(app)` inside the lifespan callback results in `trace_id = 0`
on all requests. Root cause: Starlette builds the middleware stack when the ASGI app
processes its first connection (the lifespan connection itself), before the lifespan
callback runs. Middleware added inside the lifespan callback is too late.

Correct placement:

```python
app.add_middleware(RequestLoggingMiddleware)
FastAPIInstrumentor().instrument_app(app)   # module level, after add_middleware
```

`configure_telemetry()` can remain in the lifespan because OTel uses a `ProxyTracer`
that automatically switches to the real `TracerProvider` once `set_tracer_provider()`
is called — even if the Tracer was obtained before that call.

#### Middleware order (outer → inner = last-added → first-added)

In Starlette, middleware added **last** is **outermost** (processes requests first).

```
OTelMiddleware (outermost — added last via instrument_app)
  → RequestLoggingMiddleware (inner — added first via add_middleware)
    → Router
```

OTel creates the span first; `RequestLoggingMiddleware` reads it via
`trace.get_current_span()`.

#### `SQLAlchemyInstrumentor` requires `engine.sync_engine`

```python
# Wrong — AsyncEngine rejects synchronous event listeners
SQLAlchemyInstrumentor().instrument(engine=engine)

# Correct
SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
```

The instrumentation library registers SQLAlchemy synchronous event hooks
(`before_cursor_execute` etc.). `AsyncEngine` explicitly blocks these to prevent
misuse; `AsyncEngine.sync_engine` exposes the underlying synchronous engine.

#### trace_id format

OTel stores `trace_id` as a 128-bit integer. Convert to the standard hex-32 form with:

```python
span = trace.get_current_span()
trace_id = format(span.get_span_context().trace_id, "032x")
```

All-zeros (`"00000000000000000000000000000000"`) means no active span — indicates
a middleware ordering problem.

---

## Key Takeaways

### What did I learn?

I learned the three-layer structure of OpenTelemetry: `TracerProvider` (global
configuration), `Tracer` (obtained per module), and `Span` (per operation). I also
learned how `FastAPIInstrumentor` works by inserting an ASGI middleware that creates
a span for each incoming request, making the trace context available downstream via
`trace.get_current_span()`.

### What would I do differently?

I would read the Starlette middleware lifecycle more carefully before placing
`instrument_app()` in the lifespan. The scaffolding step assumed lifespan was the
right place, but it caused a hard-to-diagnose `trace_id = 0` bug. I would also know
upfront that `AsyncEngine` requires `.sync_engine` for SQLAlchemy instrumentation.

I would also use `structlog.get_logger()` from the very first scaffold draft, not
`logging.getLogger()`. The inconsistency was caught immediately but added unnecessary
rework.

### What surprised me?

Two things:

1. **The middleware stack is frozen before the lifespan runs.** I expected lifespan
   to be an early startup hook, but Starlette builds the middleware stack during the
   very first ASGI connection — which is the lifespan connection itself. This means
   any `add_middleware` call inside the lifespan callback has no effect.

2. **`ProxyTracer` allows decoupled initialization.** Even though `instrument_app()`
   is called at module level (before `configure_telemetry()` runs), the spans are
   correctly recorded. OTel's proxy mechanism transparently switches to the real
   provider once it is set, without requiring re-instrumentation.

### What is worth remembering for future goals?

- `FastAPIInstrumentor().instrument_app(app)` **must** be at module level, after
  `app.add_middleware(...)`.
- `SQLAlchemyInstrumentor().instrument()` takes `engine=engine.sync_engine`, not the
  `AsyncEngine`.
- Middleware order in Starlette: last added = outermost = runs first. When two
  middlewares must execute in sequence, add the inner one first.
- `trace_id = "000...000"` (32 zeros) is the diagnostic signal that OTel has no
  active span — check middleware order first.
- `BatchSpanProcessor` failure is graceful by design. Export errors appear in logs
  but never propagate to request handlers.

---

## Related

- `app/core/telemetry.py` — `configure_telemetry()` implementation
- `app/main.py` — initialization order
- `docs/learning-notes/concepts/structlog-vs-stdlib-logging.md` — logging library comparison
- S5-4 — Jaeger setup (will visualize the spans generated here)
