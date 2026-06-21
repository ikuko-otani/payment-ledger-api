# Pre-Publication Verification Review

Conducted: 2026-06-21 (post-S8-7, pre-S9)

Second-round review verifying that the 6 tech debt items (TD-038–TD-043)
identified in the first review have been correctly resolved, plus a final
sweep for public-release readiness.

First review: `docs/reviews/pre-publication-code-review.md`

---

## Fix Verification Results

### TD-038: BalanceResponse missing currency code — ✅ Verified

- `app/schemas/account.py:49`: `currency: str` (ISO 4217) added to
  `BalanceResponse`.
- `app/api/v1/routes/accounts.py:65-76`: populated from `account.currency`
  on both the cache-hit (line 72) and cache-miss (line 76) paths. Bonus:
  `find_by_id` lookup also adds a proper 404 for non-existent accounts
  (lines 65-67).
- Test: `tests/test_balance.py:242` asserts
  `resp.json()["currency"] == "EUR"`.

### TD-039: FX rate exact-date-only lookup — ✅ Verified

- `app/repositories/currency_repository.py:103-119`:
  `effective_date <= effective_date` + `.order_by(effective_date.desc()).limit(1)`
  — exactly the recommended form.
- Tests: `tests/test_transactions.py:631`
  (`test_weekend_date_uses_most_recent_exchange_rate` — Saturday falls back
  to Friday's rate, asserts `converted_amount_usd == 1080`) and `:703`
  (`test_no_exchange_rate_on_or_before_date_returns_422` — no rate
  on-or-before date → 422). Good pairing: happy path + floor case.

### TD-040: Unbounded list endpoints — ✅ Verified

- `/accounts` (`accounts.py:38-39`), `/currencies` (`currencies.py:29-30`),
  `/exchange-rates` (`exchange_rates.py:34-35`) all now have
  `limit=Query(default=20, ge=1, le=100)` and
  `offset=Query(default=0, ge=0)` — identical constraints to
  `/transactions:47-48`, `/ledger`, `/audit-logs`.
- Repository layer wired through: `list_all`/`list_exchange_rates` accept
  and apply `.limit().offset()` (`currency_repository.py:56-60,88`,
  `account_repository.py:52-56`).
- Tests: `test_accounts.py:163`, `test_currencies.py:165,187` verify page
  contents and offset behavior.

### TD-041: Idempotency key not bound to request body — ✅ Verified

- `app/dependencies/idempotency.py:86`:
  `fingerprint = sha256(body).hexdigest()`.
- Stored atomically with the pending marker in a single `SET NX`
  (lines 89-92) — the fingerprint and `status:pending` are one JSON value,
  so there is no window where a pending key exists without its fingerprint.
- Mismatch → 422 (lines 109-114); test `test_idempotency.py:301`
  (`test_same_key_different_body_returns_422`) confirms.

### TD-042: `redis.keys()` in write path — ✅ Verified

- `app/api/v1/routes/transactions.py:76`: replaced with
  `redis.scan_iter(match=pattern, count=100)`.
- Repo-wide grep confirms no `redis.keys()` remains anywhere in `app/`.
  (The only `.keys()` hit is `dict.keys()` in
  `app/services/transaction_service.py:95`.)

### TD-043: Japanese comments in core files — ⚠️ Verified with one residual

- `app/db/session.py` and `tests/conftest.py` (the two files named in
  the first review) are fully English. ✅
- **Residual**: `alembic/env.py:9` —
  `load_dotenv()  # ← これがないと .env が読まれない`.
  This core infrastructure file was not in TD-043's original scope but
  should have been caught in the S8-7 sweep.
- Registered as **TD-044** (Low). Planned for **S8-8**.

---

## Regression Check — Pass

- **Balance cache tests**: unaffected. `test_balance.py:183` still asserts
  `balance == 2500` on the endpoint; the cache-hit path returns the same
  value plus currency.
- **Stripe-style replay**: intact. Replay with identical body → fingerprint
  matches, `"response" in stored` → 200 (`idempotency.py:116-118`);
  `test_same_idempotency_key_replays_200_on_second_request` still valid.
- **Exact-date FX**: `<=` is a superset of `==`, so an exact-date row
  still wins (`ORDER BY effective_date DESC` puts it first). Existing
  exact-date conversion tests unaffected.
- **`POST /transactions` end-to-end trace**: validation → double-entry /
  currency check → FX resolve-once (TD-030) → flush → `db.commit()`
  (line 71) → cache invalidation via `scan_iter` (lines 72-79) →
  `idempotency.cache()` (line 82). Ordering is correct: commit precedes
  both invalidations (preserves the TD-018 fix).

### Minor note (not a regression blocker)

The balance endpoint now issues a `find_by_id` PK lookup on every request,
including cache hits (`accounts.py:65`). TD-015 had reduced the cache-hit
path to zero DB queries (~37ms). This reintroduces one indexed PK
round-trip on the hot path. Semantically necessary for currency + 404, but
storing currency alongside balance in the cached value would restore
DB-free cache hits. Registered as **TD-046** (Low).

---

## Updated Verdicts

### Currency consistency: Pass (was Partial)

Every monetary response now carries its ISO 4217 code. FX lookup no longer
rejects weekends/holidays. No remaining path returns a bare amount.

### Pagination: Pass (was Partial, 3/6)

All 6 list endpoints use identical `limit(20, ge=1, le=100)` /
`offset(0, ge=0)` constraints with stable `ORDER BY`.

### Integration test coverage: 3 of 4 gaps closed

| Gap (from first review) | Status |
|---|---|
| Same-key / different-body → 422 | ✅ Closed (`test_idempotency.py:301`) |
| Currency in balance response | ✅ Closed (`test_balance.py:242`) |
| List-endpoint boundary tests | ✅ Closed (`test_accounts.py:163`, `test_currencies.py:165,187`) |
| Concurrent in-flight 409 | ❌ Still open |

The concurrent in-flight 409 test (`pending` → 409 branch,
`idempotency.py:120-123`) is the only untested business-critical
idempotency state. Registered as **TD-045** (Medium). Planned for **S8-8**.

### H-1 (transaction boundaries): Confirmed correct

Single commit in the route, invalidations strictly after commit.

### H-2 (idempotency design): Resolved

Fingerprint bound atomically to the pending marker; mismatch → 422,
in-flight → 409, success → 200 replay, failure → key released.

---

## Portfolio Signal Assessment

### Strongest signals of senior engineering judgment

1. **Idempotency state machine is genuinely correct, not cargo-culted.**
   Atomic `SET NX` carrying both fingerprint and status in one value, a
   clean three-outcome model (replay 200 / in-flight 409 / mismatch 422),
   and key release on failure for safe retries. The design note in the
   docstring shows the author reasoned about the race windows.

2. **Disciplined money handling.** BIGINT minor units throughout,
   `Decimal`/`ROUND_HALF_UP` for FX, currency FKs to a `currencies`
   table, scale via `decimal_places`, and currency on every response.

3. **Consistency as a system property.** The same pagination contract, the
   same stable `ORDER BY`, the same repository abstraction across every
   endpoint — and a tech-debt ledger (TD-001→043) that shows defects
   being found, tracked, and closed methodically. The `<=`-with-DESC
   FX fallback is the textbook-correct answer.

### Remaining risk areas

- `alembic/env.py:9` Japanese comment — small, but contradicts the
  stated English-only convention on a file reviewers open. (TD-044, S8-8)
- Missing concurrent-409 test leaves the impression that concurrency
  claims are asserted in prose but not proven in CI. (TD-045, S8-8)
- Balance cache-hit DB lookup quietly walks back a documented latency
  optimization (TD-015) without acknowledging the trade-off. (TD-046)

### Overall readiness: Ready with minor fixes

The codebase is technically sound and the six original debt items are
genuinely resolved. Two ~10-minute fixes (TD-044 + TD-045, planned as
S8-8) clear the only items a careful reviewer would flag.

---

## Tech Debt Registered

| ID | Priority | Description | Planned |
|----|----------|-------------|---------|
| TD-044 | Low | `alembic/env.py:9` Japanese comment residual | S8-8 |
| TD-045 | Medium | No concurrent in-flight 409 idempotency test | S8-8 |
| TD-046 | Low | Balance cache-hit path re-introduces DB query | Backlog |
