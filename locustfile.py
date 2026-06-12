"""Locust load test scenarios for payment-ledger-api.

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
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime

from locust import HttpUser, between, task

ADMIN_EMAIL = os.environ.get("LOCUST_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("LOCUST_ADMIN_PASSWORD", "changeme")


class LedgerUser(HttpUser):
    """Simulates one authenticated client of the ledger API."""

    wait_time = between(1, 3)

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
                    {
                        "account_id": self.debit_account_id,
                        "direction": "debit",
                        "amount": 1000,
                        "currency": "USD",
                    },
                    {
                        "account_id": self.credit_account_id,
                        "direction": "credit",
                        "amount": 1000,
                        "currency": "USD",
                    },
                ],
            },
        )

    @task(3)
    def get_balance(self) -> None:
        self.client.get(
            f"/api/v1/accounts/{self.debit_account_id}/balance",
            params={"as_of": datetime.now(UTC).isoformat()},
        )
