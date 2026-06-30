"""Integration tests for GET /metrics endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_metrics_returns_200(async_client: AsyncClient) -> None:
    response = await async_client.get("/metrics")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_content_type_is_plain_text(async_client: AsyncClient) -> None:
    response = await async_client.get("/metrics")
    assert "text/plain" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_metrics_exposes_http_request_histogram(
    async_client: AsyncClient,
) -> None:
    # Make a request first so the histogram has data to report
    await async_client.get("/health")

    response = await async_client.get("/metrics")
    assert "http_request_duration_seconds" in response.text
