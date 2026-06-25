# ARCHITECTURE.md — payment-ledger-api

> **payment-ledger-api** is a double-entry bookkeeping REST API
> built with FastAPI, SQLAlchemy 2.0 (async), PostgreSQL, and Alembic.
> It enforces the same ledger invariants and idempotency conventions used inside
> payment processors such as Mollie, Stripe, and Revolut.

---

## 1. Domain Overview

The API implements the **double-entry accounting** principle: every financial event
is recorded as two equal and opposite entries — a debit on one account and a
credit on another. This guarantees that the ledger is always balanced, providing
an audit-proof record of every money movement.

Three core entities model the domain:

| Entity        | Role                                                              |
|---------------|-------------------------------------------------------------------|
| `accounts`    | Chart of accounts (Asset, Liability, Equity, Revenue, Expense)    |
| `transactions`| Immutable header representing a single financial event            |
| `entries`     | Debit/credit lines; each transaction has ≥ 2 entries that balance |

---

## 2. ER Diagram

```
accounts
─────────────────────────────
id            UUID  PK
code          TEXT  UNIQUE          -- e.g. "1100", "2000"
name          TEXT
type          TEXT                  -- ASSET | LIABILITY | EQUITY | REVENUE | EXPENSE
currency      VARCHAR(3)            -- ISO 4217 (EUR, USD, JPY …)
is_active     BOOLEAN
created_at    TIMESTAMPTZ
updated_at    TIMESTAMPTZ

        │ 1
        │
        │ N
entries ─────────────────────────────────────────────────────────────
id              UUID  PK
transaction_id  UUID  FK → transactions.id  ON DELETE RESTRICT
account_id      UUID  FK → accounts.id      ON DELETE RESTRICT
direction       TEXT  -- DEBIT | CREDIT
amount          BIGINT CHECK (amount > 0)   -- minor currency unit (cents)
currency        VARCHAR(3)
created_at      TIMESTAMPTZ
        │ N
        │
        │ 1
transactions
─────────────────────────────
id               UUID  PK
description      TEXT
status           TEXT  -- PENDING | POSTED | VOIDED
posted_at        TIMESTAMPTZ
created_at       TIMESTAMPTZ
metadata         JSONB
```

Invariant: `SUM(amount) WHERE direction='DEBIT' = SUM(amount) WHERE direction='CREDIT'`
per `transaction_id`.

---

## 3. Key Design Decisions

The numbered design decisions below use this document's own sequence.
Formal ADR files with their own numbering live in `docs/adr/`.

### Money as BIGINT (minor units)

**Decision**: Store all monetary amounts as `BIGINT` representing the smallest
currency unit (cents, pence, yen). A separate currency VARCHAR(3) column carries
the ISO 4217 code.

**Rationale**: Stripe and Mollie both use this convention internally and in their
public APIs (`amount=1099` = €10.99). Integer arithmetic eliminates floating-point
rounding errors entirely. The per-currency decimal scale (2 for EUR/USD, 0 for JPY)
is looked up from a small reference table or hardcoded per ISO 4217.

**Trade-off**: Cryptoassets with 8-decimal precision require a different strategy
(e.g. `NUMERIC(30,8)`). That is out of scope for MVP.

---

### Double-entry balance enforced at the application layer (primary) + DB constraint trigger (safety net)

**Decision**: Double-entry balance is enforced at two layers. The FastAPI service
layer validates `SUM(DEBIT entries) == SUM(CREDIT entries)` before persisting,
providing early user-friendly error messages. A PostgreSQL
`CONSTRAINT TRIGGER trg_check_entries_balance … DEFERRABLE INITIALLY DEFERRED`
acts as a safety net checked at `COMMIT`, catching any write that bypasses the
service layer (e.g. direct SQL, migration scripts).

**Rationale**: A plain `CHECK` constraint operates per-row and cannot compare
aggregate values across multiple `entries` rows. The deferred constraint trigger
fires once per row at `COMMIT` time, when all entries for the transaction are
present, and raises `check_violation` (SQLSTATE 23514) if debits ≠ credits.

---

### Idempotency key storage

**Initial decision (MVP)**: `transactions.idempotency_key TEXT UNIQUE`.
PostgreSQL's unique index provided strong atomicity with zero additional
infrastructure.

**Updated in S2-3**: Migrated to Redis-backed idempotency with a 24 h TTL
and removed the `idempotency_key` column from `transactions`.
See `docs/adr/001-redis-for-idempotency-key.md` for the full rationale.

**Summary**: Redis allows the idempotency check to be decoupled from the DB
write transaction, enables TTL-based expiry, and clears the key on failure so
retries are not blocked by a previously failed request. Redis is a hard
dependency on the write path — if unavailable, `POST /transactions` returns
500 rather than silently skipping the check, because a skipped idempotency
check could create duplicate transactions (correctness over availability).

**Evolved in S7 — request fingerprinting and response replay**:

The implementation now follows a two-phase Redis state machine with
Stripe-style semantics (`app/dependencies/idempotency.py`):

1. **Phase 1 (new request)**: `SET NX` stores a JSON payload containing a
   SHA-256 fingerprint of the request body and `"status": "pending"`.
2. **Phase 2 (on success)**: the pending marker is overwritten with the
   serialised response body, so future duplicates replay the original `200`
   response instead of returning `409 Conflict`.
3. **Fingerprint mismatch**: if the same idempotency key is reused with a
   different request body, the server returns `422 Unprocessable Entity` —
   preventing silent request substitution.
4. **Failure cleanup**: if the request raises an exception after the key is
   acquired, the key is deleted so the client can retry with the same key.

**Consequence**: the idempotency layer is no longer a simple duplicate gate;
it is a correctness mechanism that guarantees *exactly-once semantics* for
successful requests and safe retry for failed ones. The trade-off is
increased Redis storage per key (response body cached alongside the
fingerprint) and slightly more complex error-handling logic.

---

### Immutable transaction log

**Decision**: `transactions` and `entries` rows are never updated or deleted after
`status = POSTED`. Corrections are modelled as new reversal transactions.

**Rationale**: Immutability is the foundation of financial audit trails. Every
balance at any point in time can be reconstructed by replaying the log. This also
simplifies CDC (Change Data Capture) for downstream analytics.

---

## 4. Tech Stack

| Layer            | Technology                              |
|------------------|-----------------------------------------|
| API              | FastAPI (async)                         |
| Validation       | Pydantic v2                             |
| ORM              | SQLAlchemy 2.0 (async + asyncpg driver) |
| Migrations       | Alembic                                 |
| Database         | PostgreSQL 16                           |
| Auth             | JWT (PyJWT)                             |
| Testing          | pytest + pytest-asyncio + testcontainers|
| Containerisation | Docker + Docker Compose               |
| CI               | GitHub Actions (lint / mypy / test)     |
| Observability    | structlog (JSON) + OpenTelemetry        |

---

## 5. Running Locally

```bash
git clone https://github.com/ikuko-otani/payment-ledger-api
cd payment-ledger-api
docker compose up          # PostgreSQL + API on :8000
# http://localhost:8000/docs
```

---

## 6. Authentication & Authorization Design

> Covers JWT-based auth, RBAC role enforcement, and the `get_current_user`
> dependency. Each subsection explains **what was chosen and what was
> deliberately rejected**.

### 6.1 Why JWT over server-side sessions

**Decision**: Issue a signed JWT (HS256) on successful login. Every subsequent
request carries the token in the `Authorization: Bearer <token>` header; the
server validates the signature and extracts the payload without touching the
database or a session store.

**What was rejected**: HTTP sessions backed by a server-side store (Redis,
PostgreSQL). In that model the server keeps a session table, looks up every
request by session ID, and must propagate session state across all API
instances.

**Rationale**:
- *Statelessness*: any API pod can validate a JWT independently; no shared
  session store is required. This makes horizontal scaling (adding pods behind
  a load balancer) a configuration change rather than an architectural one.
- *Simplicity*: for a single-service MVP with two roles and no logout
  requirement, the extra operational cost of a session store (cache warm-up,
  TTL management, failover) adds complexity with no benefit.
- *Industry convention*: REST + JWT is the dominant pattern for service-to-
  service and mobile clients; it matches what payment-processing teams
  (Stripe, Mollie) expect to review.

**Trade-off — what JWT gives up**:
- *Instant revocation* is hard. A valid token stays valid until expiry even
  after a user is disabled. Mitigation options include: short-lived tokens
  (15 min), a token blocklist in Redis, or opaque reference tokens. These
  are deferred to a post-MVP hardening sprint.
- *Payload size*: every request carries the full token. For APIs with very
  large claims sets, this adds per-request overhead vs. a session ID cookie.

### 6.2 Why RBAC over ABAC

**Decision**: Implement Role-Based Access Control with two roles: `admin`
(full read/write) and `auditor` (read-only). The role is stored on the
`users` table and checked in the FastAPI dependency layer.

**What was rejected**: Attribute-Based Access Control (ABAC), which evaluates
a policy against a combination of user attributes, resource attributes, and
environment context (e.g. "user from department=Finance may read transactions
where currency=EUR during business hours").

**Rationale**:
- *Scope fit*: the current business requirement is exactly two roles with a
  clear write/read split. RBAC expresses this in a single enum column; ABAC
  would require a policy engine (Open Policy Agent, Casbin) and a schema for
  attribute propagation — significant complexity for zero extra capability.
- *Auditability*: "what can this user do?" is answered by reading one column.
  With ABAC the answer depends on the full policy set and the resource being
  accessed, which is harder to audit.
- *Evolution path*: if a third role emerges (e.g. `reconciler` with narrow
  write access), adding an enum value and a new dependency check is a one-day
  change. If the access model grows to dozens of fine-grained rules, migrating
  to ABAC at that point is still possible without rewriting the existing RBAC
  checks.

### 6.3 Why native PostgreSQL enum for the `role` column

**Decision**: Define `role` as a PostgreSQL native `ENUM` type (`CREATE TYPE
user_role AS ENUM ('admin', 'auditor')`), mapped to a Python `enum.Enum`
via SQLAlchemy's `Enum(UserRole, native_enum=True)`.

**What was rejected**:
- *VARCHAR with CHECK constraint*: allows arbitrary strings to be inserted
  before the constraint fires; no type-level guarantee at the ORM layer.
- *Application-level enum only (native_enum=False)*: stores the value as
  VARCHAR in PostgreSQL, losing the DB-side type guarantee and the ability
  to introspect valid values from the schema.

**Rationale**:
- *Type safety at two layers*: PostgreSQL rejects any value not in the enum
  at write time; SQLAlchemy raises a validation error before the query even
  reaches the DB. Defense in depth.
- *Schema clarity*: `\d users` in psql shows `user_role` as the column type,
  making the valid role set discoverable without reading application code.
- *Consistency with direction/type columns*: `entries.direction` and
  `accounts.type` already use the same pattern in this codebase.

**Trade-off**:
- Adding a new role requires `ALTER TYPE user_role ADD VALUE 'reconciler'`
  in an Alembic migration *plus* a new enum member in Python. The two must be
  deployed together. This coupling is acceptable at two roles; with 10+ roles
  a VARCHAR approach avoids migration churn.

### 6.4 Why uniform error messages for auth failures

**Decision**: All authentication and authorization failures return a generic
`401 Unauthorized` or `403 Forbidden` with a fixed message
(`"Not authenticated"` / `"Not enough permissions"`). The response body does
not reveal whether the token was missing, expired, malformed, or signed with
the wrong secret, nor whether the user ID exists in the database.

**What was rejected**: Specific error messages such as `"Token expired"`,
`"User not found"`, or `"Invalid signature"`. These messages are common in
tutorials and developer-friendly APIs but leak information useful to
attackers.

**Rationale**:
- *User enumeration prevention*: if the API returned `"User not found"` for
  a valid token referencing a non-existent UUID, an attacker could brute-force
  UUIDs to determine which users exist. A uniform `401` closes this channel.
- *Token structure disclosure*: distinguishing `"expired"` from `"invalid
  signature"` tells an attacker whether a forged token passed structural
  validation — useful feedback for crafting further attacks.
- *OWASP API Security Top 10*: uniform errors directly address API2
  (Broken Authentication) and API3 (Excessive Data Exposure).

**Trade-off**:
- *Developer experience*: during development a `401` with no context is
  frustrating. Mitigation: detailed error codes in server-side structured
  logs (structlog) visible to operators but not returned to clients.

### 6.5 Why embed role/is_active in the JWT payload (no per-request DB query)

**Decision**: At login (`POST /api/v1/auth/login`), embed `role` and
`is_active` as additional claims in the JWT payload alongside `sub`
(user UUID). `get_current_user` (`app/core/deps.py`) decodes the token
and constructs a lightweight `TokenUser` Pydantic model from the claims —
no database query is issued on any authenticated request.

See `docs/adr/006-jwt-claims-no-db-per-request.md` for the full ADR.

**What was rejected**: The previous implementation resolved the JWT `sub`
claim into a full `User` ORM object via `SELECT * FROM users WHERE id = ?`
on every request. This DB round-trip dominated the latency budget even
after Redis caching optimisations in S7-4.

**Rationale**:
- *Latency reduction*: the only fields consumed downstream are `id`,
  `role`, and `is_active` — all available at login time. Embedding them
  in the token turns `get_current_user` into a pure in-memory decode
  (microseconds, not milliseconds).
- *Dependency elimination*: `get_current_user` no longer requires an
  `AsyncSession`, removing the DB session from the critical path of
  every authenticated request.
- *Consistency with §7.1*: the statelessness argument for JWT (any pod
  can validate independently) is undermined if every request still hits
  the DB for user data. Embedding claims completes the stateless design.

**Trade-off — stale claims window**:
- Role changes and deactivations applied in the database are **not
  reflected in existing tokens** until those tokens expire. The window
   is bounded by `ACCESS_TOKEN_EXPIRE_MINUTES` (configured to 30 min in this deployment).
- Mitigation options (deferred to post-MVP): short-lived tokens (5 min)
  + silent refresh, or a token blocklist in Redis.
- For a portfolio project with no production users, the 30-minute
  revocation window is an acceptable trade-off.

---

## 7. Multi-Currency Design

### Rounding policy: ROUND_HALF_UP for currency conversion

**Decision**: Use `ROUND_HALF_UP` (always round 0.5 away from zero) when converting
amounts to USD cents via `Decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP)`.

**What was rejected**: `ROUND_HALF_EVEN` (banker's rounding — Python's built-in `round()`
default), which rounds 0.5 to the nearest even number (2.5 → 2, 3.5 → 4).

**Rationale**:
- *Customer expectations*: ROUND_HALF_UP matches how most people learn to round.
  A customer who sees ¥100 converted at a rate of 0.005 expects $0.01, not $0.00.
- *ISO 20022 / fintech convention*: payment processors (Stripe, Mollie) and most
  central bank guidelines specify ROUND_HALF_UP for customer-facing amounts.
- *Determinism*: ROUND_HALF_UP produces the same result regardless of whether
  the input is odd or even, making individual transactions easier to audit.

**Trade-off**:
- ROUND_HALF_EVEN minimises cumulative rounding error across large datasets
  (useful in statistical aggregations). For per-transaction conversion where
  each row is audited independently, ROUND_HALF_UP is preferred.

### Hub-and-Spoke base currency (USD)

**Decision**: Store a single `converted_amount_usd` (BigInteger, USD cents) on every
`entries` row, computed at write time from the `ExchangeRate` table. USD is the base.

**What was rejected**: Storing all N×(N-1)/2 currency pair rates, or converting
on read (re-computing at query time using the current rate).

**Rationale**:
- *N rates vs N² pairs*: with N currencies, only N rates (each→USD) are required
  instead of N×(N-1)/2 pairs. At 10 currencies: 10 vs 45 rows to maintain.
- *Point-in-time snapshot*: the USD value at transaction date is immutable. Using
  today's rate to value a past transaction violates accounting immutability.
- *Simplicity*: a single base currency makes cross-currency reporting trivial —
  SUM(converted_amount_usd) is always comparable regardless of source currency.

**Trade-off**:
- Two-hop conversions (JPY→USD→EUR for EUR reporting) accumulate two rounding
  operations. Accepted at MVP scale; a dedicated reporting currency column can
  be added per reporting requirement in a future sprint.
- Changing BASE_CURRENCY requires a full data migration of all `converted_amount_usd`
  values — treat the constant as immutable once production data exists.

### JSONB for audit log snapshot columns

**Decision**: Store `before_value` and `after_value` in `audit_logs` as
PostgreSQL `JSONB` columns rather than plain `JSON`, a normalized
snapshot table, or application-level serialised strings.

**What was rejected**:
- *Plain `JSON`*: stored as text; no field-level indexing; slower reads
  when searching within the payload.
- *Normalised snapshot table*: a separate table with one row per changed
  field (entity_id, field_name, old_value, new_value). Strictly relational
  but requires a new migration every time a new auditable field is added.
- *Event Sourcing (full event log)*: all state is derived by replaying
  events; no current-state table. Provides maximum auditability but adds
  significant operational complexity (event store, projection rebuild) that
  is out of scope for MVP.

**Rationale**:
- *Schema agility*: adding a new field to `transactions` or `accounts` does
  not require a migration to `audit_logs`. The JSONB snapshot captures
  whatever the service layer serialises at write time.
- *GIN index support*: `JSONB` supports GIN indexes, enabling efficient
  field-level queries such as `before_value->>'status' = 'PENDING'` without
  a full table scan. `JSON` (text storage) cannot use GIN indexes.
- *Point-in-time snapshot*: capturing the full object state before and
  after each write avoids the need to replay a chain of events to answer
  "what did this record look like at time T?".

**Trade-off**:
- JSONB storage is slightly larger than plain JSON due to binary encoding
  overhead, and write throughput is marginally lower due to parsing at
  insert time. At the expected volume (one audit row per business
  transaction), this is negligible.
- Querying deeply nested JSONB structures requires PostgreSQL-specific
  operators (`->`, `->>`, `@>`). This couples reporting queries to
  PostgreSQL. Accepted as a deliberate choice; the project already depends
  on PostgreSQL-specific features (UUID type, ENUM types, BIGINT).

### `Numeric(18,8)` for exchange rate storage, not `Float`

**Decision**: Store `exchange_rates.rate` as PostgreSQL `NUMERIC(18,8)` (mapped to
Python `decimal.Decimal`), not as `FLOAT` or `REAL`.

**What was rejected**: `FLOAT` / `REAL` (IEEE 754 binary floating-point). These types
represent decimal fractions as sums of powers of two, so `0.1` cannot be stored
exactly — it becomes `0.1000000000000000055511151231257827021181583404541015625`.

**Rationale**:
- *Exact arithmetic*: `NUMERIC` performs decimal arithmetic with no binary approximation.
  `SELECT 0.1 + 0.2` returns `0.3` exactly; with `FLOAT` it returns `0.30000000000000001`.
- *Error compounding*: a single conversion step introduces a negligible error, but when
  amounts are summed across thousands of entries for reporting, IEEE 754 drift accumulates.
  `NUMERIC` keeps every intermediate result exact.
- *Audit alignment*: the `rate` stored in `exchange_rates` is the rate recorded at
  transaction time and must reproduce the exact `converted_amount_usd` on demand.
  A binary-float rate cannot guarantee this reproduction.
- *Python `Decimal` symmetry*: SQLAlchemy maps `NUMERIC` ↔ `decimal.Decimal`, which uses
  the same decimal model. Mixing `Decimal` in Python with a `FLOAT` column would silently
  lose precision at the ORM boundary.

**Trade-off**:
- `NUMERIC` arithmetic is slower than native `FLOAT` arithmetic (software decimal vs.
  hardware FPU). At one exchange-rate lookup per transaction write, this overhead is
  immeasurable. It would matter only for bulk statistical computations — which belong
  in a reporting layer, not the OLTP write path.
- Precision `(18,8)` supports rates up to `9_999_999_999.99999999` with 8 decimal places,
  covering all fiat currencies and most crypto assets at realistic exchange rates.

### Append-only AuditLog over Event Sourcing (MVP)

**Decision**: Record auditable state changes by appending rows to `audit_logs`
(one row per write, carrying `before_value` and `after_value` as JSONB snapshots)
rather than adopting a full Event Sourcing architecture.

**What was rejected**: Event Sourcing — a pattern where all application state changes
are stored exclusively as an ordered, immutable log of domain events. Current state
is never stored directly; it is derived by replaying the event stream (or by maintaining
a projection). Frameworks: Axon (Java), EventStoreDB, Kafka with compaction.

**Rationale**:
- *Complexity cost at MVP scale*: Event Sourcing requires an event store, projection
  rebuilds on schema change, eventual consistency between projections and queries,
  and specialised tooling for snapshotting and event versioning. None of this
  infrastructure exists in the current stack.
- *Current-state queries remain simple*: with append-only AuditLog, `SELECT * FROM
  accounts WHERE id = ?` still returns current state directly. In full Event Sourcing,
  answering the same query requires either a materialised projection or a full replay —
  a non-trivial read path for an OLTP API.
- *Point-in-time reconstruction*: `before_value` / `after_value` JSONB snapshots allow
  answering "what did this record look like at time T?" without replaying a chain of
  events. For the current audit requirements (regulatory query, dispute resolution),
  snapshot-based lookup is sufficient.
- *Bounded scope*: the audit requirement is "who changed what and when" — a compliance
  need. Event Sourcing solves a broader architectural problem (temporal queries, CQRS,
  event-driven fan-out). Adopting it for a single compliance requirement would be
  over-engineering.

**Future migration path** (not closed):
If the system grows to require real-time event-driven fan-out (e.g. downstream
accounting systems, fraud detection pipelines), the append-only `audit_logs` table
can be treated as a lightweight outbox. A future sprint could introduce an Outbox
pattern (Debezium CDC → Kafka) without rewriting the current write path. Full Event
Sourcing remains an option if projection-based reporting becomes a first-class
requirement.

**Trade-off**:
- Append-only AuditLog cannot reconstruct *all* application state from the log alone —
  only the fields captured in `before_value` / `after_value`. A bug that skips the
  audit write leaves a gap. Event Sourcing has no such gap by construction.
  Mitigation: the service layer always writes `audit_logs` inside the same database
  transaction as the entity write (atomicity via PostgreSQL).

---

## 8. Observability & Caching Design

> Covers structlog (JSON logging), OpenTelemetry + Jaeger (distributed tracing),
> and a Redis-backed Cache-Aside layer for `GET /accounts/{id}/balance`.
> Each subsection is written as an interview-ready entry: decision, rationale,
> and trade-offs.

### 8.1 Why async SQLAlchemy over sync

**Decision**: Use SQLAlchemy 2.0's async engine with the `asyncpg` driver and
`AsyncSession` throughout the service layer (`app/services/*.py`), rather than
the classic synchronous `Session` + `psycopg2` combination.

**What was rejected**: Sync SQLAlchemy, relying on FastAPI's automatic
`run_in_threadpool` wrapping for sync route handlers and dependencies.

**Rationale**:
- *Consistency with FastAPI's concurrency model*: FastAPI is built on Starlette's
  ASGI event loop. A sync DB call inside an `async def` route blocks that loop
  for every other in-flight request; FastAPI works around this by offloading
  sync calls to a thread pool, but that reintroduces a thread-per-request cost
  that async was supposed to remove. Using `AsyncSession` end-to-end keeps the
  whole request path on a single event loop with no thread-pool indirection.
- *Throughput under I/O-bound load*: this API spends most of its time waiting
  on PostgreSQL and Redis, not computing. While one request `await`s a query,
  the event loop is free to advance other requests. (Compare: PHP-FPM allocates
  one OS process per request — a process blocked on a DB query is a process
  that cannot serve anyone else until the query returns.)
- *Driver-level support*: `asyncpg` is a mature, high-performance async
  PostgreSQL driver with native `async`/`await` support, making the async
  SQLAlchemy path a first-class option rather than a compatibility shim.

**Trade-off — what async gives up**:
- *Cognitive overhead*: every DB-touching function must be `async def` and
  every call must be `await`ed; forgetting one produces confusing runtime
  errors rather than type errors.
- *Lazy-loading caveats*: SQLAlchemy's classic lazy-load pattern
  (`account.entries` triggering an implicit query) requires a greenlet bridge
  in async mode and fails with `MissingGreenlet` if accessed outside an
  awaited context (see `docs/troubleshooting/sqlalchemy-missing-greenlet-lazy-load.md`).
  This pushes the team toward explicit eager loading (`selectinload`), which is
  arguably better practice anyway but is an extra thing to learn.
- *Smaller ecosystem*: fewer async-native extensions exist compared to the
  mature sync SQLAlchemy ecosystem (e.g. some Alembic autogenerate workflows
  still assume a sync engine, requiring a small sync/async bridge).

### 8.2 Observability stack (structlog + OpenTelemetry + Jaeger)

**Decision**: Combine three tools, each responsible for one observability
pillar: **structlog** for JSON-structured application logs, **OpenTelemetry**
(OTel) for distributed-tracing instrumentation, and **Jaeger** as the trace
storage/visualisation backend. The bridge between logs and traces is the
`trace_id`: `app/middleware/logging.py` reads the active OTel span's trace ID
and binds it into every structlog entry via `structlog.contextvars`.

**What was rejected / considered**:
- *Plain stdlib `logging`*: produces unstructured text lines that are hard to
  query in a log aggregator (Loki, Datadog, CloudWatch Logs Insights all expect
  structured fields).
- *Tracing-only (no structured logs)*: traces show *where* time was spent
  across a request, but not *why* a specific request failed (e.g. validation
  error details, business-rule rejections).
- *Logs-only (no tracing)*: logs alone cannot answer "why was this single
  request slow?" across multiple internal calls — you'd need to manually
  correlate timestamps across log lines.

**Rationale**:
- *Pivot in both directions*: a slow trace in the Jaeger UI shows the
  `trace_id`; pasting that into the log aggregator surfaces every structured
  log line for that exact request — method, path, status code, latency, and
  any business-level fields the service layer chose to log. Conversely, an
  error log line carries the `trace_id`, so you can jump straight to the
  Jaeger trace and see which downstream call (DB query, Redis lookup) was slow
  or failed.
- *JSON logs are machine-first*: structlog emits one JSON object per event, so
  every field (`request_id`, `trace_id`, `latency_ms`, …) is queryable without
  regex parsing — a direct upgrade over grep-based log archaeology.
- *Jaeger as the de facto OSS trace backend*: it speaks the OpenTelemetry
  protocol natively, ships as a single Docker Compose service, and its UI
  (waterfall view of spans) is immediately legible without custom dashboards.

**Trade-off**:
- *Operational surface area*: three tools means three things that can
  misconfigure. The most subtle failure mode encountered was instrumenting
  OTel at the wrong point in the FastAPI lifespan, which silently produced
  `trace_id = "00000000000000000000000000000000"` (32 zeros — OTel's
  `INVALID_SPAN` sentinel) instead of raising an error. The fix was to
  call `instrument_app(app)` before the app starts serving requests, not
  inside the lifespan callback.
- *No metrics pillar yet*: latency percentiles and error-rate alerting
  (Prometheus + Grafana) remain a "what I would add in production" item —
  logs and traces alone cannot answer "is p99 latency degrading over the last
  hour?" without manual aggregation.

### 8.3 Caching strategy (Cache-Aside for account balances)

**Decision**: Implement the **Cache-Aside** (lazy-loading) pattern for
`GET /accounts/{id}/balance`. The service checks Redis first
(`balance:{account_id}:{as_of_date}`); on a miss it computes the balance from
PostgreSQL and writes it back to Redis with a TTL; on every transaction write,
the service explicitly deletes the cache keys for every account touched by
that transaction (see `app/repositories/account_repository.py`, `app/core/redis.py`,
`tests/test_balance_cache.py`).

**What was rejected / considered**:
- *Write-through*: update the cache synchronously every time the underlying
  data changes, so the cache is never stale. This couples every write path to
  the cache's availability and shape, and wastes cache space on balances that
  are never subsequently read.
- *TTL-only invalidation* (no explicit delete on write): simpler to implement,
  but a balance changed by a transaction would keep returning a stale cached
  value for up to the TTL window — unacceptable for a financial ledger where
  "what is my balance right now" must be exact.

**Rationale**:
- *Correctness over staleness tolerance*: a balance changes if and only if a
  transaction posts to that account. That is a precisely identifiable event,
  so explicit invalidation at write time keeps the cache always-correct — no
  race window, no "eventually consistent" caveat to explain to a user checking
  their balance.
- *Optional infrastructure*: Cache-Aside degrades gracefully. If Redis is down,
  `get_redis_client` simply yields a client that fails to connect, the cache
  read/write is skipped, and the API still serves correct results directly
  from PostgreSQL — slower, but never wrong. A write-through design would force
  a decision about what happens when the cache write fails mid-transaction.
- *TTL as a safety net, not the primary mechanism*: a TTL is still set (so an
  orphaned key — e.g. one written just before a crash prevented invalidation —
  cannot live forever), but it is a backstop, not the invalidation strategy.

**Trade-off**:
- *Invalidation must enumerate every affected key*: because the cache key
  includes `as_of_date`, a single account can have many cached entries (one
  per date queried). `tests/test_balance_cache.py::test_post_transaction_invalidates_balance_cache`
  demonstrates deleting the keys for both the debited and credited accounts —
  but a date the cache hasn't seen yet obviously can't be (and doesn't need to
  be) invalidated. A coarser per-account key (no date component) would make
  invalidation trivial at the cost of cache hit rate for historical-balance
  queries.
- *Cache stampede risk*: if many requests for the same uncached key arrive
  simultaneously, all of them miss and recompute concurrently. At current MVP
  traffic this is negligible; a production hardening pass would add a
  short-lived lock or "request coalescing" around the cache-fill step.

### 8.4 N+1 prevention strategy (selectinload / contains_eager)

**Decision**: Apply explicit eager-loading strategies to every repository
query that returns entities with relationships:

| Repository | Strategy | Why this one |
|------------|----------|-------------|
| `TransactionRepository.save()` | `selectinload(Transaction.entries)` | After flush, reload the transaction with all its entries in a single additional `SELECT … WHERE transaction_id IN (?)` query |
| `TransactionRepository.list_all()` | `selectinload(Transaction.entries)` | Batch-load entries for all transactions returned by the list query |
| `LedgerRepository.list_entries()` | `contains_eager(Entry.transaction)` | The query already `JOIN`s `transactions` for filtering/ordering; `contains_eager` tells SQLAlchemy to populate `Entry.transaction` from the joined row instead of issuing a separate query |

**What was rejected**: SQLAlchemy's default lazy loading, where accessing
`transaction.entries` or `entry.transaction` triggers an implicit query per
parent row. In async mode this is not just slow — it raises
`MissingGreenlet` unless the access happens inside an awaited context
(see `docs/troubleshooting/sqlalchemy-missing-greenlet-lazy-load.md`).

**Rationale**:
- *Predictable query count*: `selectinload` always produces exactly 2
  queries (one for parents, one `IN`-query for children) regardless of
  result set size. Without it, listing 50 transactions would fire 1 + 50
  queries.
- *`contains_eager` for pre-joined data*: when the query already contains
  a `JOIN` (e.g. `Entry.join(Transaction)` for date filtering), a second
  `selectinload` would issue a redundant query. `contains_eager` reuses
  the joined columns at zero additional cost.
- *Async safety*: explicit eager loading eliminates all implicit lazy-load
  paths, preventing `MissingGreenlet` errors at runtime.

**Trade-off**:
- Eager loading fetches related data even when the caller does not access
  it. For the current API (transactions always return their entries, ledger
  entries always include their transaction header), this is always needed.
  If a future endpoint needed transactions without entries, a separate
  repository method with no eager loading would be appropriate.
- Query count assertions (`event.listen("before_cursor_execute")` counter)
  are not yet in place; adding them would catch regressions if a future
  contributor removes an `options()` call.

---

## 9. What I Would Add in Production

- **Event sourcing** (Outbox pattern + Kafka) for reliable downstream fan-out
- **Row-level security** in PostgreSQL for multi-tenant isolation
- **Prometheus metrics** (transaction latency p99, balance drift alert)
- **Kubernetes Helm chart** for horizontal scaling

