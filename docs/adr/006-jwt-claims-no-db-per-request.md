# ADR-006 — Embed role/is_active in JWT payload; eliminate per-request DB lookup

**Date**: 2026-06-16
**Sprint**: S7-5
**Status**: Accepted

## Context

`get_current_user` (`app/core/deps.py`) previously resolved the JWT `sub` claim
into a full `User` ORM object by issuing a `SELECT * FROM users WHERE id = ?`
on every authenticated request. This DB round-trip dominated the latency budget:
after switching to a lifespan-scoped Redis client in S7-4, the cache-hit latency
dropped from ~124 ms to ~65 ms, but the DB query for `get_current_user` remained
the primary bottleneck.

The two fields actually used from the `User` object downstream are:
- `user.role` — checked by `require_admin` / `require_auditor_or_admin`
- `user.is_active` — checked in `get_current_user` itself
- `user.id` — passed to `log_action` for audit-log attribution

All three can be embedded directly in the JWT payload at login time.

## Decision

At login (`POST /api/v1/auth/login`), embed `role` and `is_active` as additional
claims in the JWT payload alongside the existing `sub` (user UUID).

`get_current_user` decodes the JWT and constructs a `TokenUser` Pydantic model
from the claims — no database query is issued. The existing `User` ORM type in
downstream signatures (`require_admin`, service layer) is replaced with
`TokenUser`.

```python
# JWT payload shape (after change)
{
    "sub": "<uuid>",
    "role": "admin",       # UserRole.value
    "is_active": true,
    "exp": <timestamp>
}
```

## Consequences

### Positive
- Eliminates one DB query per authenticated request.
- Cache-hit latency target: ~65 ms → < 10 ms (Redis itself is < 1 ms).
- `get_current_user` becomes a pure in-memory operation; no `AsyncSession`
  dependency required.

### Negative — Security trade-off (accepted)

Role changes and deactivations (`is_active = False`) applied in the database
are **not reflected in existing tokens** until those tokens expire.
The window is bounded by `ACCESS_TOKEN_EXPIRE_MINUTES` (default: 30 minutes).

**Mitigation options** (deferred to post-MVP):
- Short-lived tokens (e.g. 5 min) + silent refresh
- Token blocklist in Redis (checked on every request — reintroduces one
  Redis RTT but avoids a DB query)
- Opaque reference tokens with a per-request session lookup

For a portfolio project with a single-instance deployment and no production users,
the 30-minute revocation window is an acceptable trade-off. This trade-off is
documented here so it is visible during code review and interview discussion.

## Alternatives Considered

**In-process LRU cache for `get_current_user`**: Cache `User` by UUID for a
configurable TTL. Avoids JWT payload growth but shares the same revocation-delay
problem and adds cache-invalidation logic. Rejected: more moving parts for the
same security trade-off.

**Token blocklist in Redis**: Exact invalidation by storing revoked JTIs.
Reintroduces a Redis lookup per request, but that is an order of magnitude
cheaper than a DB query (~0.5 ms vs. ~30 ms). Deferred as a post-MVP hardening
option.

## References

- `ARCHITECTURE.md` Section 7.1 — Why JWT over server-side sessions
- `docs/tech-debt.md` TD-015 — original latency measurement
- `app/core/deps.py` — implementation
- `app/schemas/token.py` — `TokenUser` model
