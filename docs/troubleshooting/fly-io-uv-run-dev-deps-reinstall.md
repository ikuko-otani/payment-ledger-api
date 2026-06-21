# Fly.io: `uv run` re-installs dev dependencies at startup

## Error

Application returns 502 on Fly.io. Logs show:

```
Downloading mypy (14.4MiB)
Downloading ruff (10.9MiB)
Installed 36 packages in 15.27s
```

Followed by health check timeout:

```
error.message="failed to connect to machine: gave up after 15 attempts (in 8.507658138s)"
```

## Root Cause

The Dockerfile uses `uv sync --no-dev --frozen` at build time to install
only production dependencies. However, the `CMD` uses `uv run uvicorn ...`,
which triggers a full project sync (including dev dependencies) on every
container startup.

This causes:

1. ~15 seconds of dependency download/install before the app starts
2. Health check timeout (Fly.io proxy gives up after ~8 seconds)
3. Additional memory pressure from dev dependency installation

## Resolution

Add `--no-sync` to the `CMD`:

```dockerfile
# Before (broken)
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# After (fixed)
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

`--no-sync` tells `uv run` to skip the sync step and use the
already-installed virtual environment from the build stage.

## References

- [uv documentation: `uv run --no-sync`](https://docs.astral.sh/uv/reference/cli/#uv-run)
- Commit: `fix(s9-1-3): add --no-sync and reduce workers to fix Fly.io startup`
