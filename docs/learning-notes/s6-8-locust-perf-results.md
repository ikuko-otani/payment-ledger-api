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

### Step 4 — 100-user baseline run discovers TD-026 (connection pool exhaustion)

First headless run:

```bash
docker compose --profile loadtest run --rm locust -f /mnt/locust/locustfile.py \
  --host http://api:8000 --headless -u 100 -r 10 -t 60s \
  --csv=/mnt/locust/docs/loadtest/result_100users
```

Result: 4.88% error rate (2/41 `/auth/login` requests failed), aggregated
p99 ≈ 48s. The failures were
`sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached,
connection timed out, timeout 30`.

**Root cause**: `app/db/session.py`'s `create_async_engine(...)` had no
`pool_size`/`max_overflow`, so SQLAlchemy's defaults applied
(`pool_size=5, max_overflow=10` → 15 connections max). With 100 users
ramping up in 10s, `/auth/login` (the first DB call in `on_start`) blew
through that ceiling. `SHOW max_connections` confirmed PostgreSQL allows 100
— plenty of headroom for a larger pool.

**Fix (TD-026)**: set `pool_size=20, max_overflow=30` in `app/db/session.py`.

### Step 5 — Re-run after TD-026; discover TD-027 (bcrypt blocks the event loop)

Re-running the identical 100-user test: error rate dropped 4.88% → 0%
(TD-026 confirmed). But aggregated p99 got slightly *worse* (48s → 52s) —
more requests now survived long enough to queue instead of failing early on
a pool timeout.

**Root cause**: `verify_password` (`app/core/security.py`, wraps
`bcrypt.checkpw`) was called directly inside `async def login` without
`asyncio.to_thread`. Each bcrypt check (CPU-bound, ~250ms) blocked FastAPI's
single event loop — **all** concurrent requests (not just other logins)
queued behind it. Evidence: only 9/100 simulated users got past `on_start`
within the 60s window; `post_transaction` recorded zero requests.

**Fix (TD-027)**: wrapped `verify_password`/`get_password_hash`
(`app/core/security.py`) in `await asyncio.to_thread(...)`; updated call
sites in `app/api/v1/routes/auth.py`, `app/services/user_service.py`,
`tests/conftest.py`.

### Step 6 — Re-run after TD-027; discover TD-028 (single-process dev server)

Re-running again: only a marginal change (login p99 52s → 50s, total
requests 118 → 145).

💡 Both TD-026 and TD-027 fixes were correct and necessary (eliminated 500
errors; freed the event loop from bcrypt) — but the *aggregate* p99 barely
moved, which signalled the real ceiling was elsewhere.

**Root cause**: load tests run against `fastapi dev app/main.py` — FastAPI's
**development** server: a single process, single event loop, with
`--reload`/WatchFiles enabled. Even `GET /api/v1/accounts` (no bcrypt, no
unusually heavy I/O) showed p99 ≈ 28s at 100 users, confirming the bottleneck
is raw single-process request-handling capacity, not the DB pool or bcrypt.

Registered as **TD-028** (fix candidates: run via `uvicorn --workers N` or
`fastapi run`, ideally as a separate compose profile so the normal
`fastapi dev --reload` workflow is unaffected).

### Step 7 — Verify TD-028 with a one-off `uvicorn --workers 4` experiment

To test the hypothesis without permanently changing `compose.yaml` /
`Dockerfile`:

```bash
docker compose stop api
docker compose run --rm --no-deps --service-ports --name api-multiworker api \
  uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

⚠️ `uv run --no-dev` (not `--no-sync`) was required — the image's baked
`.venv` was missing production dependencies (`opentelemetry`, `cryptography`,
`grpcio`, 30 packages total) that had been added to `pyproject.toml` after
the last `docker compose build`. `--no-dev` synced those in without pulling
in dev-only deps (mypy/ruff).

Re-running the identical 100-user test against the 4-worker server:

| Workers | Requests | Failures | Req/s | Aggregated p99 | Login p99 |
|---------|----------|----------|-------|-----------------|-----------|
| 1 (dev) | 145      | 0 (0%)   | ~2.4  | 50s             | 50s       |
| 4       | 976      | 7 (0.7%) | 17.30 | 23s             | 25s       |

~6.7x more requests, p99 roughly halved → **TD-028 confirmed**: the dev
server's single-process model was the dominant bottleneck all along.

But this run also surfaced 7 new failures:
`psycopg.OperationalError: ... FATAL: sorry, too many clients already`.

### Step 8 — TD-029: per-worker connection pool sizing

`app/db/session.py`'s `pool_size=20, max_overflow=30` (TD-026) is applied
**per worker process**, not per application. With 4 workers, the
theoretical connection ceiling is 4 × (20 + 30) = 200 — but PostgreSQL
`max_connections=100`.

💡 This is the same "per-process setting × N workers" trap as PHP-FPM's
`pm.max_children` × per-child DB connections needing to stay under the
database's connection limit.

Registered as **TD-029** (Medium). Fix candidates: (1) divide
`pool_size`/`max_overflow` by worker count, (2) make pool sizing
env-configurable, (3) raise `max_connections`. Deferred to a future goal —
fixing TD-028 without TD-029 would reintroduce connection errors under load.

### Step 9 — Restore `api`, then run the official 300/500-user measurements

After the experiment, `api-multiworker` was removed and `api` restored via
`docker compose up -d api` (back to `fastapi dev` + WatchFiles).

⚠️ The first 300-user attempt was contaminated: `docker compose --profile
loadtest run --rm locust ...` (without `--no-deps`) triggered a
`Container ... Recreate` of `api-1` (config mismatch left over from the
experiment), causing a ~15-30s `uv run` dev-dependency sync mid-test — the
first wave of simulated users got `on_start login failed (0)` (connection
refused). That run was discarded and re-run with `--no-deps`.

**Decision** (user-confirmed): run the official 300/500-user measurements
against the normal single-process dev server (no `compose.yaml`/`Dockerfile`
changes), documenting TD-028/TD-029 as known limitations with fixes deferred
to a future goal — staying within the goal's time-box.

Final results across all three concurrency levels (single-process dev
server, post TD-026/TD-027 fixes):

| Users | Requests | Failures | Req/s | Aggregated p99 | Login p99 |
|-------|----------|----------|-------|-----------------|-----------|
| 100   | 133      | 0 (0%)   | 2.43  | 49s             | 49s       |
| 300   | 373      | 0 (0%)   | 6.56  | 51s             | 52s       |
| 500   | 542      | 0 (0%)   | 9.61  | 51s             | 53s       |

0% errors at all three levels. Throughput scales roughly with user count,
but p99 plateaus near the 60s test window — the single process saturates
well before 100 users, so additional load mostly adds queueing rather than
additional failures.

---

## Key takeaways

- **What I learned**: performance bottlenecks come in layers. Fixing the
  connection pool (TD-026) revealed the bcrypt event-loop block (TD-027);
  fixing that revealed the single-process dev server (TD-028); verifying
  that revealed per-worker pool sizing (TD-029). Each fix was individually
  correct and necessary, even though the *aggregate* p99 barely moved until
  the real ceiling (process count) was addressed. I also learned that
  per-process settings like SQLAlchemy's `pool_size`/`max_overflow` multiply
  by worker count — a value that's safe for one process can exceed a shared
  limit (PostgreSQL `max_connections`) once you add more workers.

- **What I would do differently**: I'd run a quick multi-worker smoke test
  earlier in the goal, since the dev-server bottleneck (TD-028) ended up
  dominating all three other findings — TD-026/TD-027's real-world impact
  only becomes visible once TD-028 is also addressed. I'd also default to
  `--no-deps` on any `docker compose run` against a service that already has
  a running container, to avoid the "Recreate" contamination from Step 9.

- **What surprised me**: how flat the aggregated p99 stayed (49s → 51s → 51s)
  across 100/300/500 users on the single-process server — once the process is
  saturated, adding more users barely changes the tail latency, it just
  queues more requests within the same 60s window. I was also surprised by
  the `uv run --no-dev` vs `--no-sync` distinction: `--no-sync` skipped
  syncing entirely and left newly-added production dependencies missing from
  `.venv`, while `--no-dev` synced production deps (without dev tooling).

- **Worth remembering for future goals**: TD-028 (multi-worker deployment)
  and TD-029 (per-worker pool sizing) are linked — any future goal that adopts
  `uvicorn --workers N` must divide/configure the connection pool in the same
  change, or it will reintroduce `too many clients already` errors. Also:
  `docker compose run --rm --no-deps --service-ports --name <name> <service>
  <cmd>` is the safe pattern for one-off experiments against an
  already-running compose stack.

---

## Related documents

- `docs/learning-notes/s6-7-locust-docker-compose.md` — S6-7 scaffold (locustfile.py, compose.yaml)
- `docs/tech-debt.md` — TD-024 (entry/account currency mismatch), TD-025 (missing ORDER BY),
  TD-026 (connection pool sizing), TD-027 (bcrypt blocks event loop),
  TD-028 (single-process dev server bottleneck), TD-029 (per-worker pool sizing)
- `app/services/transaction_service.py`, `app/services/balance.py` — TD-024 context
- `app/api/v1/routes/accounts.py`, `app/api/v1/routes/transactions.py`, `app/services/ledger_service.py` — TD-025 context
- `app/db/session.py` — TD-026 (`pool_size`/`max_overflow`), TD-029 context
- `app/core/security.py`, `app/api/v1/routes/auth.py`, `app/services/user_service.py` — TD-027 context
- `README.md` — Performance section (100/300/500-user results, multi-worker comparison)
- `docs/loadtest/result_100users_*.csv`, `result_100users_multiworker_*.csv`,
  `result_300users_*.csv`, `result_500users_*.csv` — raw locust CSV results
