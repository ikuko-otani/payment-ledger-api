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


@pytest.mark.asyncio
async def test_request_log_trace_id_is_valid_otel_span_not_zero(
    async_client: AsyncClient,
) -> None:
    cap = structlog.testing.LogCapture()
    old_processors = structlog.get_config()["processors"]
    structlog.configure(processors=[structlog.contextvars.merge_contextvars, cap])
    try:
        response = await async_client.get("/api/v1/accounts")
    finally:
        structlog.configure(processors=old_processors)

    assert response.status_code == 200

    request_log = next(e for e in cap.entries if e.get("event") == "request")
    trace_id = request_log["trace_id"]

    invalid_span_trace_id = "0" * 32
    assert trace_id != invalid_span_trace_id
    assert len(trace_id) == 32
