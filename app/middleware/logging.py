import time
import uuid
from collections.abc import Callable

import structlog
import structlog.contextvars
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # TODO: implement - clear_contextvars(), then extract/generate request_id and trace_id
        # TODO: implement - bind_contextvars(request_id=..., trace_id=...)
        start_time = time.perf_counter()
        response: Response = await call_next(request)
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        # TODO: implement - response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        return response
