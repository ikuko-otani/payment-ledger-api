from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_structlog
from app.core.telemetry import configure_telemetry
from app.db.session import engine
from app.middleware.logging import RequestLoggingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_structlog()
    configure_telemetry()
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    yield


app = FastAPI(
    title="payment-ledger-api",
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
FastAPIInstrumentor().instrument_app(app)
app.include_router(api_router)


@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "ok"}
