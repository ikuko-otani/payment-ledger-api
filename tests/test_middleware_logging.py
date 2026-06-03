"""Tests for RequestLoggingMiddleware log fields."""
from __future__ import annotations

import pytest
import structlog.contextvars
import structlog.testing

from httpx import AsyncClient


@pytest.mark.asyncio
async def test_request_log_contains_required_fields(async_client: AsyncClient) -> None:
    # TODO: implement - setup: save processors, configure [merge_contextvars, LogCapture()]
    # TODO: implement - make GET /api/v1/accounts request
    # TODO: implement - teardown: restore original processors
    # TODO: implement - assert response header "X-Request-ID" is not None
    # TODO: implement - find the "request" log entry in captured entries
    # TODO: implement - assert all 6 fields present: request_id, trace_id, method, path, status_code, latency_ms
    pass
