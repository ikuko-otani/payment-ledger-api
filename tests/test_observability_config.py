"""Tests for S5 observability/cache wiring functions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import structlog
from opentelemetry.sdk.resources import SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider

from app.core.config import settings
from app.core.logging import configure_structlog
from app.core.redis import create_redis_client, get_redis_client
from app.core.telemetry import configure_telemetry


def test_configure_structlog_wires_json_renderer_and_print_logger() -> None:
    try:
        configure_structlog()
        config = structlog.get_config()
        processor_names = [type(p).__name__ for p in config["processors"]]
        assert "JSONRenderer" in processor_names
        assert "TimeStamper" in processor_names
        assert isinstance(config["logger_factory"], structlog.PrintLoggerFactory)
    finally:
        structlog.reset_defaults()


def test_configure_telemetry_builds_provider_tagged_with_service_name() -> None:
    with patch("app.core.telemetry.trace.set_tracer_provider") as mock_set_provider:
        configure_telemetry()

    mock_set_provider.assert_called_once()
    provider = mock_set_provider.call_args[0][0]
    assert isinstance(provider, TracerProvider)
    assert provider.resource.attributes[SERVICE_NAME] == "payment-ledger-api"


def test_create_redis_client_builds_from_settings() -> None:
    mock_client = AsyncMock()
    with patch(
        "app.core.redis.aioredis.from_url", return_value=mock_client
    ) as mock_from_url:
        client = create_redis_client()

    assert client is mock_client
    mock_from_url.assert_called_once_with(
        settings.redis_url, encoding="utf-8", decode_responses=True
    )


@pytest.mark.asyncio
async def test_get_redis_client_returns_app_state_redis() -> None:
    mock_client = AsyncMock()
    mock_request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(redis=mock_client))
    )

    result = await get_redis_client(mock_request)  # type: ignore[arg-type]

    assert result is mock_client
