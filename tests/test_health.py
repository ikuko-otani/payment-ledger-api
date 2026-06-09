"""Integration tests for GET /health endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_200(async_client: AsyncClient) -> None:
    response = await async_client.get("/health")
    # TODO: implement (hint: assert status 200 and body == {"status": "ok"})
