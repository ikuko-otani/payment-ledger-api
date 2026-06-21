# Pre-Publication Code Review

Conducted: 2026-06-21 (post-S8-4, pre-S9)

Review scope: correctness, production-readiness, and API consistency
across all endpoints and business-critical paths.

---

## Critical

### TD-041: Idempotency key not bound to request body

**Location**: `app/dependencies/idempotency.py:94-98`, `app/api/v1/routes/transactions.py:65-66`

The idempotency implementation caches the first successful response under
the Idempotency-Key UUID and replays it on subsequent requests without
comparing the request body. If a client reuses the same key with a
different payload, the new transaction is silently dropped and the
original response is returned.

Stripe prevents this by storing a request fingerprint alongside the key
and returning 422 when the bodies diverge.

**Recommendation**: Hash the request body (e.g. SHA-256 of the canonical
JSON), store alongside the key in Redis, and return 422 on mismatch.

---

## Significant

### TD-038: Balance response missing currency code

**Location**: `app/schemas/account.py:47-49`, `app/api/v1/routes/accounts.py:55-69`

`BalanceResponse` returns `{"balance": 1000, "as_of": "..."}` with no
currency field. The caller cannot determine whether 1000 represents
EUR 10.00 or JPY 1000. The account model has a `currency` column -- it
should be included in the response.

**Recommendation**: Add `currency: str` (ISO 4217) to `BalanceResponse`.

### TD-039: FX rate lookup requires exact date match

**Location**: `app/repositories/currency_repository.py:96-109`, `app/services/transaction_service.py:60`

`find_exchange_rate` matches `effective_date == transaction_date`. If no
rate exists for the exact transaction date (weekends, holidays), the
endpoint returns 422. Standard practice is to use the most recent
available rate (`effective_date <= transaction_date ORDER BY
effective_date DESC LIMIT 1`).

**Recommendation**: Change to `<=` with descending sort and limit 1.

### TD-040: Unbounded list endpoints

**Location**: `app/api/v1/routes/accounts.py:34-39`, `app/api/v1/routes/currencies.py:25-29`, `app/api/v1/routes/exchange_rates.py:27-37`

Three list endpoints (`/accounts`, `/currencies`, `/exchange-rates`)
have no pagination. `/transactions`, `/ledger`, and `/audit-logs` all
use `limit` (default 20, max 100) + `offset` with validation. The three
unpatched endpoints can return arbitrarily large result sets --
particularly `/exchange-rates`, which grows daily.

**Recommendation**: Add `limit: int = Query(default=20, ge=1, le=100)`
and `offset: int = Query(default=0, ge=0)` to all three.

### TD-042: `redis.keys()` in transaction write path

**Location**: `app/api/v1/routes/transactions.py:73-76`

`KEYS balance:{id}:*` is O(N) against the full Redis keyspace and blocks
the server during execution. This runs on every `POST /transactions`.

**Recommendation**: Replace with `SCAN`, or switch to a fixed cache-key
format (`balance:{account_id}`) and delete directly.

### TD-043: Japanese comments in core files

**Location**: `app/db/session.py:11,20,29`, `tests/conftest.py:200,247`

Core infrastructure files contain Japanese comments, inconsistent with
the project's English-only code convention.

**Recommendation**: Translate remaining Japanese comments to English.

---

## Currency Consistency Verdict: Partial

**Strengths**:
- All monetary values use BIGINT minor units (no float arithmetic anywhere)
- FX conversion uses `Decimal` (Numeric 18,8) with `ROUND_HALF_UP`
- Entry currency validated against account currency (TD-024)
- `accounts.currency` and `entries.currency` have FK to `currencies.code` (TD-035)
- Currency scale managed via `currencies.decimal_places` (TD-012)

**Gaps**:
- Balance response omits currency code (TD-038)
- FX lookup requires exact date match (TD-039)

## Pagination Verdict: Partial

**Covered** (limit/offset with ge/le validation + stable ORDER BY):
- `GET /transactions` -- `limit` default 20, max 100
- `GET /ledger` -- `limit` default 20, max 100
- `GET /audit-logs` -- `limit` default 20, max 100

**Missing** (unbounded):
- `GET /accounts` -- no pagination (TD-040)
- `GET /currencies` -- no pagination (TD-040)
- `GET /exchange-rates` -- no pagination, grows daily (TD-040)

## Integration Test Gaps

**Well covered**: double-entry enforcement (balanced / unbalanced /
debit-only / credit-only / mixed-currency / currency-mismatch),
idempotency replay (Stripe-style 200), RBAC matrix
(admin / auditor / unauthenticated), JWT validation (expired / tampered /
missing claims), TOCTOU duplicate-email race (`asyncio.gather`), audit
trail for all mutations, pagination ordering, balance point-in-time with
voided exclusion, balance cache hit / miss / invalidation, multi-currency
conversion with rounding.

**Gaps**:
1. No concurrent in-flight 409 test for idempotency (`__pending__` race path)
2. No test for same idempotency key with different request body (TD-041)
3. No multi-currency balance test asserting currency in response (blocked by TD-038)
4. No boundary tests for unbounded list endpoints (blocked by TD-040)

## Tech Debt Registered

| ID | Priority | Description |
|----|----------|-------------|
| TD-038 | High | BalanceResponse missing currency code |
| TD-039 | Medium | FX rate exact-date-only lookup |
| TD-040 | Medium | Unbounded list endpoints |
| TD-041 | High | Idempotency key not bound to request body |
| TD-042 | Medium | `redis.keys()` in write path |
| TD-043 | Low | Japanese comments in core files |

## Planned Resolution

- **S8-5**: TD-038 + TD-040 (API response completeness + pagination)
- **S8-6**: TD-041 + TD-042 (idempotency hardening + Redis)
- **S8-7**: TD-039 + TD-043 (FX lookup + code cleanup)
