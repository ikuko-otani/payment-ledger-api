# S6-7: Locust Load Test Setup (docker-compose integration)

**Date**: 2026-06-12
**Branch**: `feature/s6-7-locust-docker-compose`
**Goal**: Add a `locustfile.py` with a realistic read/write scenario and a
`locust` service to `compose.yaml`, so the full load-test environment is
reproducible with `docker compose --profile loadtest up`. Actual load test
execution & measurement is out of scope (S6-8).

---

## Design decision: official `locustio/locust` image (Option A)

Two options were considered for how locust gets into the docker-compose
environment:

- **Option A** — use the official `locustio/locust` Docker image (same
  pattern as `db`/`redis`/`jaeger`, which are also pulled as prebuilt
  images). Only `compose.yaml` + `locustfile.py` change.
- **Option B** — add `locust` to `pyproject.toml` dev dependencies and run
  it via the same image as `api`. Requires `Dockerfile` changes too, because
  `Dockerfile` runs `uv sync --no-dev --frozen` — dev dependencies are not
  installed in the image as-is.

**Chosen: Option A.** Rationale:

- Zero changes to `pyproject.toml` / `Dockerfile` → no image rebuild needed
  (consistent with CLAUDE.md 6.2: rebuild only on `pyproject.toml`/`Dockerfile`
  changes).
- Matches the existing pattern for `db`/`redis`/`jaeger` (`image:` not
  `build:`).
- Option B's main advantage — running `uv run locust ...` locally on the
  host — isn't needed, since "やらないこと" excludes actual load test
  execution in S6-7.

---

## Step C Walkthrough

### Step 1 — `on_start`: login + fetch test accounts

```python
def on_start(self) -> None:
    response = self.client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    token = response.json()["access_token"]
    self.client.headers["Authorization"] = f"Bearer {token}"

    accounts = self.client.get("/api/v1/accounts").json()
    self.debit_account_id = accounts[0]["id"]
    self.credit_account_id = accounts[1]["id"]
```

Key points:

- `self.client` (from `HttpUser`) is a `requests.Session`-like object.
  Headers set on it persist across all later requests from the same
  simulated user — same pattern as `tests/conftest.py`'s `auditor_client`
  fixture (`client.headers.update({"Authorization": ...})`).
- `on_start` runs once per simulated user, before its `@task` loop starts —
  the natural place for "login".
- Account IDs are fetched dynamically via `GET /api/v1/accounts` (an
  `AuditorOrAdmin` endpoint, accessible with an ADMIN token) rather than
  hardcoded, so the scenario works in any environment with ≥2 accounts.
  `accounts[0]["id"]` is already a JSON string (no `str()` needed).

### Step 2 — `post_transaction` (weight 7): `POST /transactions`

```python
@task(7)
def post_transaction(self) -> None:
    self.client.post(
        "/api/v1/transactions",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "currency_code": "USD",
            "description": "locust load test",
            "transaction_date": date.today().isoformat(),
            "entries": [
                {"account_id": self.debit_account_id, "direction": "debit",
                 "amount": 1000, "currency": "USD"},
                {"account_id": self.credit_account_id, "direction": "credit",
                 "amount": 1000, "currency": "USD"},
            ],
        },
    )
```

Key points:

- `Idempotency-Key: str(uuid.uuid4())` — a **fresh UUID per call**. Each task
  iteration represents a new logical transaction; reusing a key would hit the
  Redis-backed idempotency check (`app/dependencies/idempotency.py`, 24h TTL)
  and return `409` on retry.
- `currency_code: "USD"` (== `BASE_CURRENCY` in
  `app/services/transaction_service.py`) takes the early-return path in
  `_get_converted_amount_usd`, avoiding any `ExchangeRate` lookup/seed data
  requirement.
- `amount: 1000` is minor units (= $10.00); both entries use the same amount
  so debit_sum == credit_sum (double-entry balance check).
- Response body isn't inspected — locust automatically records status code
  and latency for every `self.client.*` call.

### Step 3 — `get_balance` (weight 3): `GET /accounts/{id}/balance`

```python
@task(3)
def get_balance(self) -> None:
    self.client.get(
        f"/api/v1/accounts/{self.debit_account_id}/balance",
        params={"as_of": datetime.now(UTC).isoformat()},
    )
```

Key points:

- `as_of` is a **required** query param on `GET /accounts/{id}/balance`
  (`app/api/v1/routes/accounts.py`) — omitting it returns `422`.
- The balance cache key is `f"balance:{id}:{as_of.date()}"` — keyed by date
  only, so repeated calls on the same day hit the Redis cache. This makes
  the `get_balance` task a good probe for TD-015 (cache-hit latency ~99ms)
  once real load tests run in S6-8.
- `7:3` weight ratio (post:read) approximates a ledger system where postings
  are more frequent than balance lookups.

### Step 4 — `compose.yaml`: `locust` service + startup verification

```yaml
  locust:
    image: locustio/locust:2.32.4
    profiles: [loadtest]
    ports:
      - "8089:8089" # Web UI
    depends_on:
      - api
    environment:
      LOCUST_ADMIN_EMAIL: ${LOCUST_ADMIN_EMAIL:-admin@example.com}
      LOCUST_ADMIN_PASSWORD: ${LOCUST_ADMIN_PASSWORD:-changeme}
    volumes:
      - ./locustfile.py:/mnt/locust/locustfile.py:ro
    command: -f /mnt/locust/locustfile.py --host http://api:8000
```

- `profiles: [loadtest]` excludes `locust` from a normal `docker compose up`;
  it only starts with `--profile loadtest`.
- `--host http://api:8000` resolves over the docker-compose internal network
  (same convention as `DATABASE_URL=...@db:5432/...`).

**Web UI mode** — verified:

```bash
docker compose up -d                       # api/db/redis/jaeger
docker compose --profile loadtest up -d locust
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8089/
# → HTTP 200
```

**Headless mode** — verified:

```bash
docker compose --profile loadtest run --rm locust \
  -f /mnt/locust/locustfile.py --host http://api:8000 \
  --headless -u 1 -r 1 -t 10s
```

Ran for 10s and printed a summary report, then exited (exit code 1, see
below).

#### ⚠️ Expected result without seed data

```
POST /api/v1/auth/login   1   1(100.00%) | ... 401 Unauthorized
KeyError: 'access_token'
```

`admin@example.com` / `changeme` (the `.env.example` defaults) don't exist as
a real user yet, so `on_start` fails with `401` → `KeyError` on
`response.json()["access_token"]`. locust records this as a per-user error
and still completes the run normally — this confirms the **locust
service/headless command itself works**. Generating real traffic (an ADMIN
user + ≥2 accounts must exist first) is the S6-8 scope.

---

## Setup notes for S6-8 (real run)

To get `on_start` to succeed (needed before real measurements in S6-8):

1. Register a user via `POST /api/v1/users` (defaults to `AUDITOR` role).
2. Promote it to `ADMIN` directly in the DB (temporary, dev-only — does not
   change `deps.py` or any auth code):
   ```bash
   docker compose exec db psql -U ledger_user -d ledger_db \
     -c "UPDATE users SET role='ADMIN' WHERE email='<email>';"
   ```
3. Create ≥2 accounts via `POST /accounts` (as that admin), using
   `currency="USD"` to match the `locustfile.py` entries.
4. Set `LOCUST_ADMIN_EMAIL` / `LOCUST_ADMIN_PASSWORD` in `.env` to match.

---

## Related documents

- `docs/learning-notes/concepts/locust-load-testing.md` — locust concepts
  (`HttpUser`, `@task` weight, `on_start`, Web UI vs headless)
- `locustfile.py`, `compose.yaml` — implementation
- `app/dependencies/idempotency.py` — idempotency-key mechanism
- `docs/tech-debt.md` — TD-015 (balance cache-hit latency)

---

## Key takeaways

- I learned that a locust scenario is just "one virtual user's behaviour"
  (`on_start` + weighted `@task`s) — locust itself handles concurrency,
  pacing (`wait_time`), and result aggregation, so I didn't need `TaskSet`
  for a scenario this small.
- I learned that `profiles: [loadtest]` is the right way to add an
  occasionally-used service to `compose.yaml` without changing the behaviour
  of a normal `docker compose up` — the same pattern could apply to other
  optional tooling later.
- I would double-check Git Bash path handling earlier next time. The
  `/mnt/locust/locustfile.py` argument got silently rewritten to a Windows
  path until I added `MSYS_NO_PATHCONV=1` — worth remembering as a general
  rule for any Unix-style path passed to `docker compose run` from Git Bash,
  not just this command.
- I was surprised that locust treated the `on_start` `401`/`KeyError`
  (missing seed admin user) as a normal per-user failure and still completed
  the 10s run with a full summary report and clean exit, rather than crashing
  the whole process. That gave me confidence the headless command itself is
  correct, independent of S6-8's seed-data work.
- For future goals: fetching reference IDs dynamically in `on_start`
  (`GET /api/v1/accounts`) instead of hardcoding kept the locustfile usable
  across environments — a pattern worth reusing for other scenario files.
- Worth remembering for S6-8: the ADMIN-user/account setup steps are already
  written down in this file's "Setup notes for S6-8" section, so I don't need
  to re-derive them.
