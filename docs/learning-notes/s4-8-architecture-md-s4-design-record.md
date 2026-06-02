# S4-8: ARCHITECTURE.md Design Record + S4 Integration Verification

**Date**: 2026-06-02
**Goal**: Document S4 multi-currency and audit-log design decisions in ARCHITECTURE.md (English),
and verify all five S4 endpoints via curl against a live Docker environment.

---

## Step C Walkthrough

### Step C-1: ADR-009 — Why `Numeric(18,8)` not `Float`

Added to `ARCHITECTURE.md` Section 8.

**Core reasoning**: IEEE 754 binary floating-point cannot represent decimal fractions
exactly (`0.1 + 0.2 ≠ 0.3` in floating-point arithmetic). For exchange rates that are
multiplied against amounts and stored as immutable audit records, even tiny representation
errors compound and make reproduction of past calculations impossible.

`NUMERIC(18,8)` performs exact decimal arithmetic. SQLAlchemy maps it to Python
`decimal.Decimal`, maintaining precision end-to-end from DB through ORM to service layer.

**Interview angle**: "Why not Float?" is a fintech interview staple. The answer must
cover IEEE 754, not just "floats are inaccurate" — the mechanism matters.

### Step C-2: ADR-010 — Append-only AuditLog vs Event Sourcing

Added to `ARCHITECTURE.md` Section 8.

**Core reasoning**: Event Sourcing requires an event store, projection rebuilds on
schema change, eventual consistency management, and specialised tooling. For the
current audit requirement ("who changed what and when"), append-only JSONB snapshots
answer every regulatory query without that complexity.

**Key design choice**: keeping the migration path to Event Sourcing open. The
append-only `audit_logs` table can serve as a lightweight outbox for a future
Debezium CDC → Kafka pipeline without rewriting the current write path.

**Interview angle**: "What would you change if you had to scale this?" — the answer
demonstrates awareness of Event Sourcing trade-offs without prematurely adopting it.

### Step C-3 (skipped): ER diagram update

Not part of DONE conditions; deferred.

### Steps C-4 / C-5: curl Integration Verification

Verified all five S4 endpoints against a live Docker environment after a full DB reset
(`docker compose down -v`). Key lessons from this process are recorded in Key takeaways
below.

---

## Discoveries During curl Verification

### Enum value conventions: DB vs API

All `str` enum types in this codebase follow the same pattern:

| Layer | Value | Example |
|-------|-------|---------|
| PostgreSQL ENUM | `.name` (uppercase) | `'ASSET'`, `'DEBIT'`, `'ADMIN'` |
| JSON API request/response | `.value` (lowercase) | `"asset"`, `"debit"`, `"admin"` |

SQLAlchemy `native_enum=True` stores the enum member's `.name` in PostgreSQL.
Pydantic serialises the enum member's `.value` to JSON. These are independent layers.

```python
class AccountType(str, Enum):
    ASSET = "asset"
#   ^^^^   ^^^^^^^
#   .name  .value
#   → DB   → JSON
```

This is a coherent design (DB identifiers are uppercase constants; JSON API values
follow lowercase REST conventions) but was initially an unintentional inconsistency
discovered only when verifying curl responses directly.

### DB reset procedure

When Docker volumes are removed (`docker compose down -v`), all tables are dropped.
Recreate with:

```bash
docker compose up -d          # start containers first
uv run alembic upgrade head   # run on HOST, not inside container
```

### Seed data required after DB reset

No migration seeds data. After a reset, before testing multi-currency flows, manually
create via API (in order):

1. Admin user → promote via `UPDATE users SET role = 'ADMIN'`
2. Currencies (USD, EUR)
3. Accounts (1100 ASSET, 2000 LIABILITY)
4. Exchange rate (EUR→USD, matching `effective_date` = `transaction_date`)

### API base path

All endpoints are under `/api/v1/`, not at root. E.g. `POST /api/v1/transactions`.

### Auth endpoint

Login is `POST /api/v1/auth/login` with JSON body `{"email": ..., "password": ...}`,
not `POST /auth/token` with form-encoding.

### Exchange rate and transaction date must match

`_get_converted_amount_usd()` looks up `ExchangeRate` by exact
`(from_currency_id, to_currency_id, effective_date == transaction_date)`.
A mismatch returns HTTP 422 with "No exchange rate found for EUR→USD on <date>".

---

## Key Takeaways

**What did I learn?**

I learned the difference between how SQLAlchemy and Pydantic each use a Python `str`
enum — SQLAlchemy stores `.name` (the member identifier) in PostgreSQL, while Pydantic
serialises `.value` (the assigned string) to JSON. This two-layer behaviour is easy to
overlook because SQLAlchemy maps them transparently and everything appears to work.
The disconnect only became visible when I sent curl requests and read the Pydantic
validation errors directly.

I also practised writing architectural decision records in English at an interview-ready
level — not just "what we chose" but "what we explicitly rejected and why", with
trade-offs stated. The ADR-010 pattern of closing with a "future migration path" section
is a strong signal of senior-level thinking.

**What would I do differently?**

I would prepare a seed script (or at minimum a documented curl sequence) at the start
of the sprint rather than reconstructing it from scratch after a DB reset. The time
spent diagnosing missing data (no user, no currencies, no accounts) was avoidable.

I would also add the `/api/v1` prefix to the base URL earlier in the curl planning
phase rather than discovering it from a 404.

**What surprised me?**

The enum `.name` vs `.value` behaviour was genuinely surprising — I expected SQLAlchemy
to use `.value` since the column is a `str` enum. The fact that it uses `.name` for the
PostgreSQL ENUM type (matching the Alembic autogenerated uppercase values) is a subtle
SQLAlchemy-specific convention that is not obvious from the Python code alone.

I was also surprised that the `effective_date` on an exchange rate must exactly match
the `transaction_date` — there is no "use the most recent rate on or before the date"
fallback. This is a deliberate point-in-time snapshot design but would catch users
off-guard in a real integration.

**What is worth remembering for future goals?**

- Always check `.name` vs `.value` when using `native_enum=True` with `str` enums.
- "What did you reject and why?" is the interview question behind every ADR.
- Append-only patterns (AuditLog, immutable transactions) are the foundation of
  financial audit trails; Event Sourcing is the next step up the complexity ladder,
  not a prerequisite.
- After any DB reset: up → migrate → seed → then test. Never skip the seed step.
