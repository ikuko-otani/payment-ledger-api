.PHONY: lint format typecheck check

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy app/

check: format lint typecheck
