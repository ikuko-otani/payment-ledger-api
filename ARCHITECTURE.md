# ARCHITECTURE.md — payment-ledger-api

> **payment-ledger-api** is a production-grade double-entry bookkeeping REST API
> built with FastAPI, SQLAlchemy 2.0 (async), PostgreSQL, and Alembic.
> It demonstrates the core ledger patterns used inside payment processors such as
> Mollie, Stripe, and Revolut.

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
currency      CHAR(3)               -- ISO 4217 (EUR, USD, JPY …)
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
currency        CHAR(3)
created_at      TIMESTAMPTZ
        │ N
        │
        │ 1
transactions
─────────────────────────────
id               UUID  PK
idempotency_key  TEXT  UNIQUE
description      TEXT
currency         CHAR(3)
status           TEXT  -- PENDING | POSTED | VOIDED
posted_at        TIMESTAMPTZ
created_at       TIMESTAMPTZ
metadata         JSONB
```

Invariant: `SUM(amount) WHERE direction='DEBIT' = SUM(amount) WHERE direction='CREDIT'`
per `transaction_id`.

---

## 3. Key Design Decisions

### ADR-001 — Money as BIGINT (minor units)

**Decision**: Store all monetary amounts as `BIGINT` representing the smallest
currency unit (cents, pence, yen). A separate `currency CHAR(3)` column carries
the ISO 4217 code.

**Rationale**: Stripe and Mollie both use this convention internally and in their
public APIs (`amount=1099` = €10.99). Integer arithmetic eliminates floating-point
rounding errors entirely. The per-currency decimal scale (2 for EUR/USD, 0 for JPY)
is looked up from a small reference table or hardcoded per ISO 4217.

**Trade-off**: Cryptoassets with 8-decimal precision require a different strategy
(e.g. `NUMERIC(30,8)`). That is out of scope for MVP.

---

### ADR-002 — Double-entry balance enforced at the application layer (primary) + DB constraint trigger (safety net)

**Decision**: FastAPI service layer validates `SUM(DEBIT entries) == SUM(CREDIT entries)`
before persisting. A PostgreSQL `CONSTRAINT TRIGGER … DEFERRABLE INITIALLY DEFERRED`
acts as a safety net checked at `COMMIT`.

**Rationale**: A plain `CHECK` constraint operates per-row and cannot compare
aggregate values across multiple `entries` rows. An application-layer check
provides early, user-friendly error messages. The deferred trigger catches any
bug that bypasses the service layer (e.g. direct DB writes, migration scripts).

---

### ADR-003 — Idempotency via PostgreSQL UNIQUE constraint (MVP)

**Decision**: `transactions.idempotency_key TEXT UNIQUE`. On `409 Conflict` the
API re-reads and returns the original response body.

**Rationale**: For MVP traffic, PostgreSQL's unique index gives strong atomicity
guarantees with zero additional infrastructure. Redis-based distributed locking
adds operational complexity (TTL management, cache stampede) and is deferred until
horizontal scaling requires it (> ~50 rps to the same resource).

---

### ADR-004 — Immutable transaction log

**Decision**: `transactions` and `entries` rows are never updated or deleted after
`status = POSTED`. Corrections are modelled as new reversal transactions.

**Rationale**: Immutability is the foundation of financial audit trails. Every
balance at any point in time can be reconstructed by replaying the log. This also
simplifies CDC (Change Data Capture) for downstream analytics.

---

## 4. Tech Stack

| Layer          | Technology                              |
|----------------|-----------------------------------------|
| API            | FastAPI 0.111 (async)                   |
| Validation     | Pydantic v2                             |
| ORM            | SQLAlchemy 2.0 (async + asyncpg driver) |
| Migrations     | Alembic                                 |
| Database       | PostgreSQL 16                           |
| Auth           | JWT (python-jose)                       |
| Testing        | pytest + pytest-asyncio + testcontainers|
| Containerisation | Docker + Docker Compose               |
| CI             | GitHub Actions (lint / mypy / test)     |
| Observability  | structlog (JSON) + OpenTelemetry        |

---

## 5. Running Locally

```bash
git clone https://github.com/<you>/payment-ledger-api
cd payment-ledger-api
docker compose up          # PostgreSQL + API on :8000
# http://localhost:8000/docs
```

---

## 7. Authentication & Authorization Design

> Added in S3 after implementing JWT-based auth, RBAC role enforcement, and
> the `get_current_user` dependency. These decisions explain **what was chosen
> and what was deliberately rejected**, so they can serve as interview answers
> without modification.

### 7.1 Why JWT over server-side sessions

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

### 7.2 Why RBAC over ABAC

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

### 7.3 Why native PostgreSQL enum for the `role` column

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

### 7.4 Why uniform error messages for auth failures

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

---

## 8. Multi-Currency Design (S4)

### ADR-006 — Rounding policy: ROUND_HALF_UP for currency conversion

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

### ADR-007 — Hub-and-Spoke base currency (USD)

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

### ADR-008 — JSONB for audit log snapshot columns

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

### ADR-009 — `Numeric(18,8)` for exchange rate storage, not `Float`

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

---

## 6. What I Would Add in Production

- **Event sourcing** (Outbox pattern + Kafka) for reliable downstream fan-out
- **Row-level security** in PostgreSQL for multi-tenant isolation
- **Redis-based idempotency store** with 24 h TTL at high write concurrency
- **Prometheus metrics** (transaction latency p99, balance drift alert)
- **Kubernetes Helm chart** for horizontal scaling

