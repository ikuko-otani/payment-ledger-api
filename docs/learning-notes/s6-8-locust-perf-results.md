# S6-8: Locust Load Test Execution, Analysis & README

**Date**: 2026-06-12
**Branch**: `feature/s6-8-locust-perf-results`
**Goal**: Run staged locust headless load tests (100 / 300 / 500 users), save CSV
results to `docs/loadtest/`, read p50/p95/p99 latency, address bottlenecks if
p99 > 100ms, and add a Performance section to `README.md`. Builds on the
`locustfile.py` / `compose.yaml` scaffold from S6-7
(`docs/learning-notes/s6-7-locust-docker-compose.md`).

---

## Step C Walkthrough

### Step 1 — Reuse existing ADMIN user, but create dedicated USD accounts

The DB already had an `admin@example.com` (role `ADMIN`, created 2026-06-02)
and two EUR accounts (`1100 Cash EUR`, `2000 Payables EUR`) from earlier goals.
At first glance it looked like these could be reused directly for the load
test — no new user/account setup needed.

#### Design note: `entries[].currency` vs `Account.currency` (→ TD-024)

Checking `app/services/transaction_service.py` and
`app/services/balance.py` showed that:

- `create_transaction` validates that all `entries[]` in *one* request share
  the same `currency`, and that debit_sum == credit_sum — but **never compares
  `entry.currency` against `Account.currency`**.
- `calculate_balance` sums raw `Entry.amount` (minor units in
  `entry.currency`) with no currency filter at all.

`locustfile.py`'s `post_transaction` always sends `currency_code: "USD"` and
`entries[].currency: "USD"`. If posted against the existing **EUR** accounts
(1100/2000), the resulting "balance" would mix EUR-cents (the existing seed
entry) with USD-cents (load-test entries) — a numerically meaningless value.

**Decision**: register this gap as **TD-024** (`docs/tech-debt.md`), and avoid
triggering it for this goal by creating two **dedicated USD accounts**
(`1110 Cash USD - Locust` / `2010 AP USD - Locust`) instead of reusing the EUR
ones. Fix candidates for TD-024 itself: (1) validate
`entry.currency == account.currency` in `create_transaction`, or (2) have
`calculate_balance` sum `converted_amount_usd` instead of raw `amount`.

#### Design note: missing `ORDER BY` in list endpoints (→ TD-025)

After creating the two new USD accounts, `GET /api/v1/accounts` returned:

```
0 1100 EUR
1 2000 EUR
2 1110 USD
3 2010 USD
```

`locustfile.py`'s `on_start` originally did `accounts[0]` / `accounts[1]` —
i.e. it would have picked the **EUR** accounts again, re-triggering TD-024.

Investigating further: `list_accounts` (`app/api/v1/routes/accounts.py`) and
`list_transactions` (`app/api/v1/routes/transactions.py`) both run
`select(...)` with **no `.order_by(...)`**, so PostgreSQL doesn't guarantee
row order.

- `list_accounts` has no pagination — impact is "non-deterministic order for
  clients that assume one" (exactly what bit us here).
- `list_transactions` *is* paginated via `limit`/`offset` — `LIMIT`/`OFFSET`
  without `ORDER BY` is a classic correctness bug: pages can return duplicate
  or skipped rows under concurrent writes.
- `get_ledger_entries` and `get_audit_logs` already use `order_by` correctly
  and are unaffected.

**Decision**: register as **TD-025** (Medium — the `list_transactions` case is
a real pagination-correctness bug). Registration only; the actual `ORDER BY`
fix is out of scope for S6-8 and deferred to a future goal.

### Step 2 — Fix `locustfile.py`'s account selection

Instead of relying on list order, `on_start` now filters by currency:

```python
accounts = self.client.get("/api/v1/accounts").json()
usd_accounts = [a for a in accounts if a["currency"] == "USD"]
self.debit_account_id = usd_accounts[0]["id"]
self.credit_account_id = usd_accounts[1]["id"]
```

This is robust regardless of how many other (non-USD) accounts exist in the
DB, and regardless of `list_accounts`'s row order (TD-025).

### Step 3 — Design note: why fix `.env`, not `locustfile.py`'s fallback defaults?

`locustfile.py` reads credentials as:

```python
ADMIN_EMAIL = os.environ.get("LOCUST_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("LOCUST_ADMIN_PASSWORD", "changeme")
```

A first smoke test (`--headless -u 1 -r 1 -t 5s`) failed `on_start` with
`401 Unauthorized` on `POST /api/v1/auth/login`, because `.env` had no
`LOCUST_ADMIN_PASSWORD` entry, so the `"changeme"` fallback was used — but the
real `admin@example.com` password on this machine is `"password"` (confirmed
via a manual login curl in Step C-1a).

**Why edit `.env` and not hardcode the real password into `locustfile.py`?**

1. **Separation of config from code (12-factor app "Config")** — `locustfile.py`
   is committed to git; the real password is environment-specific data tied
   to *this* machine's DB (a user created back on 2026-06-02). Hardcoding it
   into source would leak a real credential into git history.
2. **`.env` is this project's established pattern** for environment-specific
   config/secrets (`DATABASE_URL`, `SECRET_KEY`, `REDIS_URL`, etc. all live
   there, gitignored). `.env.example` documents the *shape* (key names +
   placeholder values); `.env` holds the *actual* values for one environment.
3. **The `"changeme"` fallback is a documented convention, not a real
   credential** — it matches `.env.example`'s placeholder. The 401 we saw was
   the system correctly reporting "this environment's `.env` doesn't match the
   contract `.env.example` documents," not a bug in `locustfile.py`.
4. **PHP/Oracle analogy**: equivalent to `getenv('DB_PASSWORD') ?: 'default'`
   in PHP, where the real value lives in `.env`/`php.ini` (excluded from
   version control), never in source.

**Fix applied**: added to `.env` (gitignored, no commit needed):

```
LOCUST_ADMIN_EMAIL=admin@example.com
LOCUST_ADMIN_PASSWORD=password
```

### Step 3b — Design note: is the 2nd argument of `os.environ.get(...)` even needed?

Follow-up question: if `.env` already supplies the value, is
`os.environ.get("LOCUST_ADMIN_PASSWORD", "changeme")`'s second argument
(`"changeme"`) necessary at all?

**The `.env` → `os.environ` chain has two layers**:

1. `.env` is read by the **`docker compose` CLI**, not by the locust process —
   it's only used for `${VAR}` substitution in `compose.yaml`.
2. `compose.yaml`'s `locust` service has its own fallback:
   ```yaml
   environment:
     LOCUST_ADMIN_EMAIL: ${LOCUST_ADMIN_EMAIL:-admin@example.com}
     LOCUST_ADMIN_PASSWORD: ${LOCUST_ADMIN_PASSWORD:-changeme}
   ```
   This `environment:` block is what actually sets `os.environ` *inside* the
   locust container — and it already has its own `:-changeme` default.

**Conclusion**: as long as locust runs via
`docker compose --profile loadtest run ...`, `LOCUST_ADMIN_PASSWORD` is
*always* present in the container's environment (either `.env`'s value or
`compose.yaml`'s `:-changeme`). So `locustfile.py`'s own `"changeme"` default
is effectively dead code on this execution path.

**But not entirely unnecessary**: if `locustfile.py` were ever run outside
this compose service (e.g. `uv run locust -f locustfile.py --host ...`
directly on the host — "Option B" considered and rejected in S6-7),
`compose.yaml`'s `environment:` block wouldn't apply, and
`os.environ.get("LOCUST_ADMIN_PASSWORD")` (no default) would return `None`.
`json={"password": None}` would then fail as a **422** (Pydantic type error)
rather than a clear **401** (wrong credentials) — a more confusing failure
mode. Keeping the default gives a more predictable failure and makes the
script self-contained/portable.

**Trade-off**: `"changeme"` is now duplicated in two places (`compose.yaml`
and `locustfile.py`) — a minor "two sources of truth" smell, but low-stakes
enough that it doesn't warrant a tech-debt entry.

---

## Key takeaways

_(to be filled in at goal closeout per CLAUDE.md 8.4)_

---

## Related documents

- `docs/learning-notes/s6-7-locust-docker-compose.md` — S6-7 scaffold (locustfile.py, compose.yaml)
- `docs/tech-debt.md` — TD-024 (entry/account currency mismatch), TD-025 (missing ORDER BY)
- `app/services/transaction_service.py`, `app/services/balance.py` — TD-024 context
- `app/api/v1/routes/accounts.py`, `app/api/v1/routes/transactions.py`, `app/services/ledger_service.py` — TD-025 context
