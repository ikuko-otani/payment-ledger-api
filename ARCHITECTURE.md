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

<!-- TODO: explain statelessness, horizontal scaling, trade-offs -->

### 7.2 Why RBAC over ABAC

<!-- TODO: explain 2-role model, why ABAC is overkill for MVP scope -->

### 7.3 Why native PostgreSQL enum for the `role` column

<!-- TODO: explain type safety, SQLAlchemy mapping, migration cost trade-off -->

### 7.4 Why uniform error messages for auth failures

<!-- TODO: explain information-leak prevention, 401 vs 403 distinction -->

---

## 6. What I Would Add in Production

- **Event sourcing** (Outbox pattern + Kafka) for reliable downstream fan-out
- **Row-level security** in PostgreSQL for multi-tenant isolation
- **Redis-based idempotency store** with 24 h TTL at high write concurrency
- **Prometheus metrics** (transaction latency p99, balance drift alert)
- **Kubernetes Helm chart** for horizontal scaling

