"""Tests for S5 observability/cache wiring functions.

Unlike the integration-style tests elsewhere in this suite, these target
*configuration* functions whose job is to call a third-party SDK with the
right arguments — so the meaningful assertion is "were the right arguments
passed and is cleanup wired up", not "does the SDK work" (that's the SDK's
own test suite's responsibility).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import structlog
from opentelemetry.sdk.resources import SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider

from app.core.cache import get_redis_client
from app.core.config import settings
from app.core.logging import configure_structlog
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


@pytest.mark.asyncio
async def test_get_redis_client_builds_from_settings_and_closes_on_exit() -> None:
    mock_client = AsyncMock()
    with patch(
        "app.core.cache.aioredis.from_url", return_value=mock_client
    ) as mock_from_url:
        gen = get_redis_client()
        client = await anext(gen)
        assert client is mock_client
        mock_from_url.assert_called_once_with(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )

        with pytest.raises(StopAsyncIteration):
            await anext(gen)

    mock_client.aclose.assert_awaited_once()
