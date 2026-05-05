from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(
    title="payment-ledger-api",
    version="0.1.0",
    debug=settings.debug,
)


@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "ok"}
