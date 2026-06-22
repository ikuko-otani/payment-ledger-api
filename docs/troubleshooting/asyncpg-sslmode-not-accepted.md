# asyncpg: `sslmode` query parameter not accepted

## Error

```
TypeError: connect() got an unexpected keyword argument 'sslmode'
```

Or, after stripping `sslmode` without setting `ssl=False`:

```
ConnectionResetError
```
(asyncpg attempts SSL by default, but internal Fly.io Postgres does not support it)

## Root Cause

Fly.io Postgres sets `DATABASE_URL` with `?sslmode=disable`. The `asyncpg`
driver does not recognize `sslmode` as a connection parameter — it uses `ssl`
instead. SQLAlchemy's asyncpg dialect does not translate between the two.

When `sslmode=disable` is simply removed from the URL, asyncpg defaults to
attempting an SSL connection, which fails on Fly.io's internal network.

## Resolution

Parse the URL, extract `sslmode`, and pass the equivalent `ssl` parameter
via `connect_args`:

```python
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

def _asyncpg_url(url: str) -> tuple[str, dict[str, object]]:
    parts = urlsplit(url)
    connect_args: dict[str, object] = {}
    if parts.query:
        qs = parse_qs(parts.query)
        sslmode = qs.pop("sslmode", [None])[0]
        if sslmode == "disable":
            connect_args["ssl"] = False
        cleaned = urlencode(qs, doseq=True)
        parts = parts._replace(query=cleaned)
    return urlunsplit(parts), connect_args

url, connect_args = _asyncpg_url(settings.database_url)
engine = create_async_engine(url, connect_args=connect_args)
```

## References

- asyncpg connection docs: `ssl` parameter (not `sslmode`)
- Applied in: `app/db/session.py`, `scripts/seed_demo_user.py`
- Commit: `fix(s9-1-5): strip sslmode from DATABASE_URL for asyncpg compatibility`
