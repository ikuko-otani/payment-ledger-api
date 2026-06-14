# S7-2: Multi-worker + Connection Pool Tuning (TD-028/029/030)

> Date: 2026-06-14
> Branch: `feature/s7-2-multiworker-connection-pool`
> PR: #63

## Goal

Three related items were intentionally kept in a single goal (not split):

- **TD-028**: run the API as a production-equivalent multi-worker server.
- **TD-029**: make the SQLAlchemy connection pool size configurable and
  right-size it for the multi-worker setup.
- **TD-030**: fix the `_get_converted_amount_usd` N+1 (up to `3 * N` queries
  per transaction) discovered during S6 review.

DONE conditions (from the Sprint Tracker):

1. `compose.yaml`/`Dockerfile` `CMD` is a multi-worker configuration.
2. `pool_size`/`max_overflow` configurable via env vars (worker-count basis).
3. Re-run the 100-user locust test; p99 should improve from S6-8's 49s.
4. All existing tests green.
5. `_get_converted_amount_usd` calls reduced to a maximum of 3 queries per
   transaction, with a new test added.

---

## Step C-1: Make `pool_size`/`max_overflow` configurable (TD-029)

💡 TD-026 (S6-8) had hardcoded `pool_size=20, max_overflow=30` directly in
`create_async_engine(...)` as an emergency fix for connection-pool
exhaustion. That was fine for a single-process server, but once TD-028
introduces multiple worker processes, each worker gets its **own** pool —
the hardcoded values would multiply by the worker count and could exceed
PostgreSQL's `max_connections`.

**`app/core/config.py`** — added two new `Settings` fields:

```python
db_pool_size: int = 5
db_max_overflow: int = 10
```

pydantic-settings maps these to `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` env vars
automatically (case-insensitive field name → env var name).

**`app/db/session.py`** — read the pool config from `settings` instead of
hardcoding it:

```python
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)
```

**`.env` / `.env.example`**:

```
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
```

⚠️ The actual numeric defaults (5/10) were chosen together with TD-028's
worker count (4): `4 workers × (5 + 10) = 60` connections, comfortably under
PostgreSQL's `max_connections=100` (confirmed via `SHOW max_connections` in
S6-8). This sizing decision belongs to Step C-1 conceptually, but its
correctness could only be validated after Step C-2 (worker count) and
Step C-3 (locust run).

✅ Verification: `uv run pytest -q tests/test_*` still green (config change
only, no behavior change to single-worker dev).

---

## Step C-2: Multi-worker `CMD` with dev/prod split (TD-028)

💡 The core design question: how do we run 4 uvicorn workers in
production-equivalent mode, **without breaking** the local dev workflow
(`fastapi dev` + WatchFiles hot-reload + source bind mount)?

Decision: split the responsibility between `Dockerfile` and `compose.yaml`.

**`Dockerfile`** — `CMD` becomes the production-equivalent default:

```dockerfile
# production-equivalent default — multi-worker, no auto-reload.
# Local development overrides this via compose.yaml's `command:` (fastapi dev).
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

**`compose.yaml`** — the `api` service overrides `CMD` with `command:` for
local dev, so WatchFiles hot-reload keeps working with the existing source
volume mount:

```yaml
services:
  api:
    build: .
    # ...
    # Dockerfile's CMD now runs the production-equivalent
    # multi-worker server (uvicorn --workers 4, no auto-reload).
    # For local development, override it with `fastapi dev` so
    # WatchFiles hot-reload keeps working with the source bind mount
    # below. To exercise the multi-worker command locally (e.g. for a
    # locust run), comment out this `command:` line and run
    # `docker compose up -d --build api`.
    command: uv run fastapi dev app/main.py --host 0.0.0.0 --port 8000
    volumes:
      - .:/app
      - /app/.venv
      - /var/run/docker.sock:/var/run/docker.sock
```

⚠️ Easy-to-miss point: `command:` in `compose.yaml` overrides `CMD` in the
Dockerfile entirely — it's not "Dockerfile CMD + extra args", it's a full
replacement. So `docker compose up` always runs `fastapi dev` (dev mode)
unless the `command:` line is commented out, in which case the image's own
`CMD` (multi-worker uvicorn) takes over.

✅ Verification (dev mode unchanged):
```bash
docker compose logs api | grep -i "watchfiles\|uvicorn"
# → "Started reloader process [...] using WatchFiles"
```

---

## Step C-3: Re-run the 100-user locust test

To exercise the multi-worker + pool-fixed path, the `command:` override in
`compose.yaml` was temporarily commented out, then:

```bash
docker compose up -d --build api
```

```bash
MSYS_NO_PATHCONV=1 docker compose --profile loadtest run --rm locust \
  -f /mnt/locust/locustfile.py \
  --host http://api:8000 --headless -u 100 -r 10 -t 60s \
  --csv=/mnt/locust/docs/loadtest/result_100users_s7_2_multiworker
```

⚠️ Hit a known Git Bash issue here: MSYS rewrites `/mnt/...` absolute paths
into Windows paths before handing them to Docker, so the bare command failed
with `Could not find 'C:/Users/.../mnt/locust/locustfile.py'`. This was
already documented in
`docs/troubleshooting/pytest-testcontainers-host-vs-docker-session-lifecycle.md`
(section 6) and `docs/learning-notes/s6-7-locust-docker-compose.md` — the fix
is the `MSYS_NO_PATHCONV=1` prefix shown above. Lesson re-applied: check
`docs/troubleshooting/` *before* debugging a Docker/Git-Bash path issue.

**Results** (`docs/loadtest/result_100users_s7_2_multiworker_*.csv`):

| Metric | S6-8 baseline (single worker, pool=20/30) | S7-2 (4 workers, pool=5/10 each) |
|---|---|---|
| Aggregated p99 | 49s | **22s** |
| Failures | 7 (`FATAL: sorry, too many clients already`, in an earlier unfixed-pool 4-worker experiment) | **0** |
| Request count | — | 830 |

After the run, the `command:` override was restored and re-verified:

```bash
docker compose up -d api
docker compose logs api | grep -i "watchfiles\|uvicorn"
# → "Started reloader process [11] using WatchFiles"
```

✅ DONE条件3 satisfied: p99 dropped ~55% (49s → 22s), 0 failures.

---

## Step C-4: Fix the `_get_converted_amount_usd` N+1 (TD-030)

💡 The old `_get_converted_amount_usd(db, entry, ...)` resolved
`from_currency`, `to_currency` (USD), and the `ExchangeRate` row **inside the
per-entry loop** — even though `currency_code` and `transaction_date` are the
same for every entry in one transaction. With N entries that's up to `3 * N`
queries against `currencies`/`exchange_rates`.

Same shape as TD-024 (S7-1): "resolve once, apply many" — see
[[sqlalchemy-query-reuse]].

**`app/services/transaction_service.py`** — split into two functions:

```python
async def _resolve_usd_conversion_rate(
    db: AsyncSession,
    currency_code: str,
    transaction_date: date,
) -> Decimal:
    """Resolve the conversion rate from currency_code to USD for transaction_date.

    - If currency_code == BASE_CURRENCY: returns Decimal("1") (identity, no query).
    - Otherwise: looks up ExchangeRate(from=currency_code, to=USD, date=transaction_date)
      and returns its `rate`.
    - Raises HTTP 422 if currency_code/USD is unknown, or no matching rate exists.

    Called once per transaction (not once per entry) -- currency_code and
    transaction_date are transaction-level values shared by every entry.
    """
    if currency_code == BASE_CURRENCY:
        return Decimal("1")
    # ... resolve from_currency, to_currency (USD), ExchangeRate (3 queries total)
    return exchange_rate.rate


def _convert_amount_usd(amount: int, rate: Decimal) -> int:
    """Apply a USD conversion rate to a minor-unit amount (no DB access)."""
    converted = (Decimal(amount) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(converted)
```

`create_transaction` now resolves the rate once, before the entries loop:

```python
conversion_rate = await _resolve_usd_conversion_rate(
    db, payload.currency_code, payload.transaction_date
)
converted_amounts = [
    _convert_amount_usd(entry.amount, conversion_rate) for entry in payload.entries
]
```

**`tests/test_transactions.py`** — new test
`test_non_usd_transaction_resolves_conversion_rate_once`: seeds EUR→USD at
1.10, creates a 4-entry EUR transaction, and uses
`event.listen(engine.sync_engine, "before_cursor_execute", ...)` to capture
every SQL statement issued during `create_transaction`. Filters for
statements touching `currencies`/`exchange_rates` and asserts
`len(conversion_queries) <= 3` — before the fix this would have been 12
(`3 * 4 entries`), after the fix it's 3 regardless of entry count. Also
asserts `converted_amount_usd == 550` (`500 * 1.10`) on every entry.

Full write-up of *how* the query-counting works (and why
`engine.sync_engine`, why scope the listener with try/finally, why filter by
table name) is in
[[sqlalchemy-query-counting-in-tests]]
(`docs/learning-notes/concepts/sqlalchemy-query-counting-in-tests.md`).

✅ DONE条件5 satisfied.

---

## Step C-5: tech-debt.md + final verification

Moved TD-028, TD-029, TD-030 from "Open Items" to "Resolved" in
`docs/tech-debt.md`, each entry summarizing the fix and linking to the
relevant evidence (loadtest CSVs, the new test, this note).

Final full suite run:

```bash
uv run pytest -q
```

```
112 passed, 2 warnings in 151.34s (0:02:31)
TOTAL  868  57  93%
Required test coverage of 85% reached. Total coverage: 93.43%
```

(111 → 112 tests: +1 for TD-030's new test. Coverage 92.24% → 93.43%.)

The two warnings (testcontainers Redis `@wait_container_is_ready`
deprecation, and `datetime.utcnow()` deprecation in
`tests/test_idempotency.py:308`) are pre-existing and out of scope for this
goal.

✅ DONE条件4 satisfied. All 5 DONE conditions met → PR #63 created and merged.

---

## Key takeaways

- I learned the pool-sizing math for multi-worker async SQLAlchemy: each
  worker process gets its own connection pool, so the total ceiling is
  `workers × (pool_size + max_overflow)`, and that total must stay under
  PostgreSQL's `max_connections`. TD-026's single-process `pool_size=20,
  max_overflow=30` would have meant `4 × 50 = 200` connections under TD-028's
  4 workers — way over `max_connections=100`. Scaling the pool *down* to
  5/10 per worker (`4 × 15 = 60`) was the right move precisely because the
  worker count went *up*.
- I learned a clean way to keep a production-equivalent `Dockerfile CMD`
  while preserving the local dev hot-reload workflow: put the
  production default in `CMD`, and let `compose.yaml`'s `command:` fully
  override it for dev. The override is a complete replacement, not an
  addition — that's worth remembering since it's easy to assume Compose
  "appends" to the image's CMD.
- I learned a mocking-free way to assert "this code issues at most N
  queries" using SQLAlchemy's `before_cursor_execute` event on
  `engine.sync_engine`, scoped with `event.listen`/`event.remove` around just
  the call under test, then filtering captured statements by table name. This
  is the same general pattern I'd reuse for any future N+1 regression test.
- What I'd do differently: I hit the Git Bash `/mnt/...` → Windows path
  rewrite issue again when running the locust command, even though it was
  already documented in `docs/troubleshooting/` from S6-7. Next time I should
  check `docs/troubleshooting/` *before* running any `docker compose run`
  command that includes a `/mnt/...` path, not after it fails.
- What surprised me: TD-029 (pool sizing) alone — combined with TD-028's
  extra worker processes — produced a much bigger latency improvement (p99
  49s → 22s, ~55%) than TD-027's bcrypt-to-thread fix did on its own in S6-8
  (52s → 50s, marginal). The earlier fix removed a *correctness* problem
  (errors → 0%) but the pool/worker combination is what actually unblocked
  *throughput*. Good reminder that a fix can be "correct" without being
  "fast", and the two need separate verification.
- Worth remembering for future goals: the "resolve once per transaction,
  apply per entry" refactor pattern (TD-024 in S7-1, TD-030 here) keeps
  showing up wherever a per-row loop does a lookup that's actually constant
  across the whole request. When reviewing new per-entry loops, check first
  whether the lookup inside actually varies per entry.

## Related

- [[sqlalchemy-query-counting-in-tests]] — query-counting technique used in
  TD-030's test.
- `docs/tech-debt.md` — TD-028, TD-029, TD-030 (Resolved, S7-2).
- `docs/loadtest/result_100users_s7_2_multiworker_*.csv` — locust results.
- `docs/troubleshooting/pytest-testcontainers-host-vs-docker-session-lifecycle.md`
  — Git Bash `/mnt/...` path rewrite issue (section 6).
