"""Domain-layer exceptions.

Services raise these instead of `fastapi.HTTPException` so they remain
usable (and unit-testable) without a FastAPI request context. `app/main.py`
registers a single `@app.exception_handler(DomainError)` that maps
`status_code` to an HTTP response.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for errors raised by the service layer."""

    status_code: int = 500

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class ValidationError(DomainError):
    """Request data is well-formed but violates a business rule. -> 422."""

    status_code = 422


class ConflictError(DomainError):
    """The request conflicts with existing state (e.g. duplicate). -> 409."""

    status_code = 409
