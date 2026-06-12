# Locust load testing: core concepts

> Date: 2026-06-11 | Goals: S6-7 (locust + docker-compose setup), S6-8 (actual run)
> Purpose: Explain what locust is, where it runs in this project's docker-compose
> setup, and the meaning of `User`, `@task` weight, and `on_start` before writing
> `locustfile.py`.

---

## 1. What locust is

Locust simulates many "virtual users" sending real HTTP requests to a target API,
then aggregates the results (response time, requests/sec, failure rate) into a live
dashboard or CLI summary.

Conceptually it's the automated, managed version of writing a script that loops
"send a request, record how long it took" hundreds of times in parallel — but locust
handles concurrency, pacing, and result aggregation for you. What you write is just
**one virtual user's behaviour**, in `locustfile.py`:

- `on_start` — what this user does once, before its first task (e.g. log in)
- `@task` methods — what this user repeats over and over, with a wait between each

---

## 2. `HttpUser` and `@task`

```python
class LedgerUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        ...

    @task(7)
    def post_transaction(self) -> None:
        ...

    @task(3)
    def get_balance(self) -> None:
        ...
```

- **`HttpUser`** — a locust base class that gives each simulated user a
  `self.client`, a `requests.Session`-like object pre-configured with the
  `--host` base URL. Every `self.client.get(...)` / `.post(...)` call is a real
  HTTP request and is timed/recorded automatically.
- **`wait_time`** — how long a simulated user "thinks" between tasks. `between(1, 3)`
  picks a random delay (1–3s) each time, approximating a human pausing between
  actions rather than hammering the API in a tight loop.
- **`@task(weight)`** — registers a method as something this user *might* do.
  The integer is a **relative weight**, not a percentage or a count. With
  `@task(7)` and `@task(3)`, locust picks `post_transaction` roughly 7 times for
  every 3 times it picks `get_balance` (≈ 70/30 split) — chosen here to mimic a
  ledger system where postings are more frequent than balance lookups.

> Older locust tutorials also mention `TaskSet` — a way to group related tasks into
> a sub-class for organizing larger scenarios (e.g. "checkout flow" vs "browsing
> flow"). This project only has two flat tasks on one `User`, so `TaskSet` isn't
> needed; `@task` directly on `HttpUser` is the simpler, more common modern style.

---

## 3. `on_start`: per-user setup

`on_start(self)` runs **once per simulated user**, before that user's task loop
begins. It's the natural place to do anything that should happen "at login time":

```python
def on_start(self) -> None:
    response = self.client.post("/api/v1/auth/login", json={...})
    token = response.json()["access_token"]
    self.client.headers["Authorization"] = f"Bearer {token}"
```

Because `self.client.headers` is set once in `on_start`, every subsequent
`self.client.post(...)` / `.get(...)` call from that user automatically carries the
`Authorization` header — same idea as `tests/conftest.py`'s `auditor_client` fixture
setting `client.headers.update({"Authorization": ...})` after login.

`on_start` is also a convenient place to fetch IDs the tasks will reuse repeatedly
(e.g. `GET /api/v1/accounts` once, then store two account IDs as
`self.debit_account_id` / `self.credit_account_id`), instead of re-fetching them on
every task iteration.

---

## 4. Where locust actually runs (this project's setup)

```
┌─────────────────────────────────────────────┐
│  docker compose --profile loadtest up        │
│                                               │
│  ┌──────────────┐   HTTP    ┌──────────────┐ │
│  │   locust     │ ────────▶ │     api      │ │
│  │  container   │ "api:8000"│  container   │ │
│  │ (locustio/   │           │  (FastAPI)   │ │
│  │  locust image)│          │      │       │ │
│  │ locustfile.py│           │      ▼       │ │
│  │ mounted in   │           │  db / redis  │ │
│  └──────────────┘           └──────────────┘ │
│        ▲                                     │
│        │ http://localhost:8089 (Web UI)      │
└────────┴──────────────────────────────────────┘
```

- locust runs **inside its own container** (the official `locustio/locust` image —
  see the A-vs-B comparison this goal started with: using the prebuilt image avoids
  any `pyproject.toml` / `Dockerfile` changes, the same pattern as `db`/`redis`/`jaeger`).
- `--host http://api:8000` means `self.client.get("/api/v1/accounts")` resolves to
  `http://api:8000/api/v1/accounts`, reaching the `api` container over the
  docker-compose internal network — `api:8000` is **not** reachable from outside
  docker, only `db`/`redis`/etc. resolve this way (same convention as
  `DATABASE_URL=...@db:5432/...`).
- The `locust` service uses `profiles: [loadtest]`, so it is **excluded** from a
  normal `docker compose up` and only starts with
  `docker compose --profile loadtest up locust`.

---

## 5. Web UI vs. headless mode

| Mode | How to start | What happens |
|---|---|---|
| **Web UI** | `docker compose --profile loadtest up locust` (no extra flags) | locust starts a web server on `:8089`. Open `http://localhost:8089`, enter user count + spawn rate, click "Start" — runs until manually stopped. |
| **Headless** | add `--headless -u <users> -r <spawn-rate> -t <duration>` to the `command` (e.g. via `docker compose --profile loadtest run --rm locust ... --headless -u 10 -r 2 -t 1m`) | locust runs automatically for the given duration, prints a summary, and exits — no browser needed. Suited for CI or quick CLI checks. |

---

## 6. S6-7 vs. S6-8 scope

| | S6-7 (this goal) | S6-8 (next) |
|---|---|---|
| Goal | `locustfile.py` exists with ≥2 tasks; `locust` service added to `compose.yaml`; the service **starts**; headless command **confirmed** | Actually run a load test with real users/duration and read the results (latency, RPS, failure rate) |
| "Running" locust means | Confirming the container starts and the headless command is accepted (no crash) | Generating real traffic against `api` and interpreting the metrics |

Out of scope for S6-7 (per Notion "やらないこと"): running an actual load test,
wiring this into CI, or migrating to k6/Gatling.

---

## Related documents

- `locustfile.py` — the scenario definitions described above
- `compose.yaml` — `locust` service definition
- `docs/learning-notes/s6-7-locust-docker-compose.md` — Step C walkthrough and setup
  steps for the ADMIN user / test accounts needed before S6-8
- `tests/conftest.py` — `auditor_client` / `authenticated_client` fixtures, which use
  the same "log in once, reuse the token on `client.headers`" pattern as `on_start`
- `app/dependencies/idempotency.py` — why `post_transaction` needs a fresh
  `Idempotency-Key` per request
