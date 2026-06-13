FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY . .

# production-equivalent default — multi-worker, no auto-reload.
# Local development overrides this via compose.yaml's `command:` (fastapi dev).
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
