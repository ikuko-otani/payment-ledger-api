from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import DomainError
from app.core.logging import configure_structlog
from app.core.redis import create_redis_client
from app.core.telemetry import configure_telemetry
from app.db.session import engine
from app.middleware.logging import RequestLoggingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_structlog()
    configure_telemetry()
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    app.state.redis = create_redis_client()
    try:
        yield
    finally:
        await app.state.redis.aclose()


app = FastAPI(
    title="payment-ledger-api",
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
FastAPIInstrumentor().instrument_app(app)
app.include_router(api_router)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
