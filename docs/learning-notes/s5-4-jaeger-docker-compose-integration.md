# S5-4: Jaeger Container + docker compose Integration

Date: 2026-06-05
Goal: Add Jaeger to the Docker Compose stack and verify distributed traces in Jaeger UI.

## Step C Walkthrough

### Overview

S5-4 integrates the OpenTelemetry traces generated in S5-3 with a Jaeger backend running
as a Docker Compose service. The goal is to make `docker compose up` the only command
needed to start a fully observable development environment.

### Step 1: Add jaeger service to compose.yaml

Added the `jaeger` service using `jaegertracing/all-in-one:1.57`, which bundles the
Jaeger Collector, Query engine, and UI into a single container.

```yaml
jaeger:
  image: jaegertracing/all-in-one:1.57
  ports:
    - "4317:4317"   # OTLP gRPC (exporter target)
    - "16686:16686" # Jaeger UI
  environment:
    COLLECTOR_OTLP_ENABLED: "true"

Added jaeger: condition: service_started to the api service's depends_on block.

Why service_started instead of service_healthy: Jaeger all-in-one has no
healthcheck defined. Using service_healthy causes Compose to fail. OTel's
BatchSpanProcessor retries failed exports internally, so waiting for Jaeger to be
fully ready is not required.

Verification:
docker compose config --quiet
docker compose up -d
curl http://localhost:8000/health

Step 2: Verify traces in Jaeger UI

Send an authenticated request to a DB-backed endpoint, then open http://localhost:16686.

Expected span structure for GET /api/v1/accounts:

- Root: GET /api/v1/accounts (FastAPI, span.kind: server)
  - connect (SQLAlchemy — DB connection)
  - SELECT ledger_db — SELECT users (JWT validation)
  - SELECT ledger_db — SELECT accounts (actual query)
  - http send × 3 (FastAPI ASGI internal events)

Step 3: Add Observability section to README.md

Added a ## Observability section documenting how to start the stack and navigate
the Jaeger UI.

Key Takeaways

What did I learn?

I learned that jaegertracing/all-in-one is a development-only image that bundles all
Jaeger components into a single container with in-memory storage. I also learned that
Jaeger has supported OTLP natively since v1.35 — the separate Jaeger agent or Thrift
protocol setup that older tutorials reference is no longer needed.

I saw for the first time how SQLAlchemyInstrumentor produces child spans with a
db.statement tag containing the actual SQL, making it possible to identify slow
queries from the Jaeger UI without touching application logs.

What would I do differently?

I would make the first authenticated test request immediately rather than spending time
on the unauthenticated curl first. A 401 response generates no SQLAlchemy spans, so
confirming child spans requires an authenticated request from the start.

What surprised me?

The db.statement tag captures the full SQL including parameter placeholders
(WHERE users.id = %(id_1)s::UUID). Every DB query is visible in Jaeger UI without
any additional instrumentation code — SQLAlchemyInstrumentor handles it automatically
once wired to sync_engine.

What is worth remembering for future goals?

- all-in-one is memory-only: traces are lost on container restart. For persistent
traces, a separate Jaeger Collector + Elasticsearch/Cassandra backend is needed
(out of scope for this sprint, relevant for S6+).
- service_started vs service_healthy: use service_started for services without
a defined healthcheck — service_healthy on a healthcheck-less service causes
docker compose up to fail.
- 401 ≠ no trace, but 401 = no DB spans: authentication failure still generates a
FastAPI trace, but no SQLAlchemy child spans appear since the request is rejected
before the service layer. Always use an authenticated request to verify SQLAlchemy
instrumentation.
- OTLP/gRPC port 4317: the OTel standard port. If a backend does not accept traces,
verify COLLECTOR_OTLP_ENABLED=true and that port 4317 is correctly exposed.

References

- Jaeger all-in-one Docker image (https://www.jaegertracing.io/docs/1.57/getting-started/)
- OTel SQLAlchemy Instrumentation (https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/sqlalchemy/sqlalchemy.html)
- Related: docs/learning-notes/s5-3-otel-fastapi-instrumentation.md
