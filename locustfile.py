"""Locust load test scenarios for payment-ledger-api (S6-7).

Run via `docker compose --profile loadtest up locust` (Web UI on :8089) or
`docker compose --profile loadtest run --rm locust --headless ...` (CLI).
See compose.yaml for the `locust` service definition.

Two task types simulate the read/write mix of a ledger system:
  - POST /api/v1/transactions          (weight 7) -- post a balanced
    double-entry transaction between two existing accounts.
  - GET /api/v1/accounts/{id}/balance  (weight 3) -- read account balance.

Setup required before running against real data (see
docs/learning-notes/s6-7-locust-docker-compose.md):
  - An ADMIN-role user must exist (LOCUST_ADMIN_EMAIL / LOCUST_ADMIN_PASSWORD).
  - At least 2 accounts must exist (created via POST /accounts as that admin).

Note: actual load test execution & measurement is out of scope for S6-7
(see S6-8). This file only needs to start cleanly under
`docker compose --profile loadtest up`.
"""

from __future__ import annotations

import os

from locust import HttpUser, between, task

ADMIN_EMAIL = os.environ.get("LOCUST_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("LOCUST_ADMIN_PASSWORD", "changeme")


class LedgerUser(HttpUser):
    """Simulates one authenticated client of the ledger API."""

    wait_time = between(1, 3)

    def on_start(self) -> None:
        # TODO: implement (hint: locust calls on_start() once per simulated
        # user, before any @task runs -- the natural place to "log in".
        #   1. POST "/api/v1/auth/login" with json=
        #      {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        #   2. token = response.json()["access_token"]
        #   3. self.client.headers["Authorization"] = f"Bearer {token}"
        #      (self.client is a requests.Session-like object -- headers set
        #      here are sent on every later request from this user)
        #   4. GET "/api/v1/accounts" (now authenticated) and store the
        #      first two account ids as self.debit_account_id and
        #      self.credit_account_id for use in the tasks below.)
        ...

    @task(7)
    def post_transaction(self) -> None:
        # TODO: implement (hint: POST "/api/v1/transactions" with
        #   headers={"Idempotency-Key": str(uuid.uuid4())} -- a fresh UUID
        #   per call, otherwise the Redis-backed idempotency check (see
        #   app/dependencies/idempotency.py) returns 409 on any retry.
        #   json body (TransactionCreate shape):
        #     {
        #       "currency_code": "USD",
        #       "description": "locust load test",
        #       "transaction_date": <today as "YYYY-MM-DD">,
        #       "entries": [
        #         {"account_id": str(self.debit_account_id),
        #          "direction": "debit", "amount": 1000, "currency": "USD"},
        #         {"account_id": str(self.credit_account_id),
        #          "direction": "credit", "amount": 1000, "currency": "USD"},
        #       ],
        #     }
        #   Using "USD" for currency_code and entry currency avoids the
        #   ExchangeRate lookup in transaction_service.py (USD is
        #   BASE_CURRENCY).
        #   You'll need: import uuid; from datetime import date)
        ...

    @task(3)
    def get_balance(self) -> None:
        # TODO: implement (hint: GET
        #   f"/api/v1/accounts/{self.debit_account_id}/balance"
        #   with params={"as_of": <current UTC time, ISO format>}.
        #   You'll need: from datetime import UTC, datetime)
        ...
