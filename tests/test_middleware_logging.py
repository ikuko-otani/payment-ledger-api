"""Tests for RequestLoggingMiddleware log fields."""

from __future__ import annotations

import pytest
import structlog.contextvars
import structlog.testing
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_request_log_contains_required_fields(async_client: AsyncClient) -> None:
    cap = structlog.testing.LogCapture()
    old_processors = structlog.get_config()["processors"]
    structlog.configure(processors=[structlog.contextvars.merge_contextvars, cap])
    try:
        response = await async_client.get("/api/v1/accounts")
    finally:
        structlog.configure(processors=old_processors)

    assert response.headers.get("X-Request-ID") is not None

    request_log = next(e for e in cap.entries if e.get("event") == "request")
    assert "request_id" in request_log
    assert "trace_id" in request_log
    assert "method" in request_log
    assert "path" in request_log
    assert "status_code" in request_log
    assert "latency_ms" in request_log
