"""Integration tests for POST /api/v1/transactions (double-entry balance rule)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient


POST_ACCOUNT_URL = "/api/v1/accounts"
POST_TX_URL = "/api/v1/transactions"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_account(client: AsyncClient, name: str, account_type: str = "asset") -> uuid.UUID:
    resp = await client.post(
        POST_ACCOUNT_URL,
        json={"name": name, "account_type": account_type},
    )
    assert resp.status_code == 201
    return uuid.UUID(resp.json()["id"])


def _tx_payload(
    debit_account_id: uuid.UUID,
    credit_account_id: uuid.UUID,
    amount: str = "1000.00",
    description: str = "Test transaction",
) -> dict:
    """Build a balanced transaction payload (debit == credit)."""
    return {
        "description": description,
        "transaction_date": "2024-01-01",
        "amount": amount,
        "entries": [
            {"account_id": str(debit_account_id), "entry_type": "debit", "amount": amount},
            {"account_id": str(credit_account_id), "entry_type": "credit", "amount": amount},
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_balanced_transaction(client: AsyncClient) -> None:
    """POST /transactions with debit == credit should return 201."""
    debit_id = await _create_account(client, "Cash-Tx", "asset")
    credit_id = await _create_account(client, "Revenue-Tx", "revenue")
    response = await client.post(POST_TX_URL, json=_tx_payload(debit_id, credit_id))
    # TODO: assert 201 and that the response contains an "id"
    # Hint: assert response.status_code == 201 / assert "id" in response.json()
    assert response.status_code == 201
    assert "id" in response.json()


@pytest.mark.asyncio
async def test_unbalanced_transaction_rejected(client: AsyncClient) -> None:
    """POST /transactions with debit != credit should return 422."""
    debit_id = await _create_account(client, "Cash-Unbal", "asset")
    credit_id = await _create_account(client, "Revenue-Unbal", "revenue")
    payload = {
        "description": "Unbalanced",
        "transaction_date": "2024-01-01",
        "amount": "1000.00",
        "entries": [
            {"account_id": str(debit_id), "entry_type": "debit", "amount": "1000.00"},
            {"account_id": str(credit_id), "entry_type": "credit", "amount": "500.00"},
        ],
    }
    response = await client.post(POST_TX_URL, json=payload)
    # ✍️ Write assertions: status 422 and error detail mentions "balanced" or "debit"/"credit"
    assert response.status_code == 422
    assert "debit" in response.json()["detail"].lower() or "balanced" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_transaction_with_single_entry_rejected(client: AsyncClient) -> None:
    """POST /transactions with only 1 entry should be rejected (field_validator)."""
    debit_id = await _create_account(client, "Cash-Single", "asset")
    payload = {
        "description": "Single entry",
        "transaction_date": "2024-01-01",
        "amount": "500.00",
        "entries": [
            {"account_id": str(debit_id), "entry_type": "debit", "amount": "500.00"},
        ],
    }
    response = await client.post(POST_TX_URL, json=payload)
    # TODO: assert status code is 422 (Pydantic validation error)
    # Hint: assert response.status_code == 422
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_transaction_entries_in_response(client: AsyncClient) -> None:
    """Response body should include entries with correct entry_type values."""
    debit_id = await _create_account(client, "Cash-Resp", "asset")
    credit_id = await _create_account(client, "Revenue-Resp", "revenue")
    response = await client.post(POST_TX_URL, json=_tx_payload(debit_id, credit_id))
    assert response.status_code == 201
    entries = response.json()["entries"]
    # ✍️ Assert len(entries) == 2 and that both "debit" and "credit" appear in entry_types
    assert len(entries) == 2
    entry_types = {e["entry_type"] for e in entries}
    assert entry_types == {"debit", "credit"}
