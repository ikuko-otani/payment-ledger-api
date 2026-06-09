# S6-3: Coverage 85% Achievement + README Badge

**Date**: 2026-06-09
**Goal**: Add targeted tests to close genuine coverage gaps identified in S6-2, wire up Codecov in CI, and add a coverage badge to README.

---

## Step C Walkthrough

### What was implemented

**New tests (5 total)**:

1. `tests/test_health.py` — `test_health_returns_200`
   - Covers `app/main.py:38` (`/health` endpoint response line)
   - Uses `async_client` (admin override); no auth dependency on this route

2. `tests/test_auth_dependency.py` — `test_jwt_missing_sub_claim_returns_401`
   - Covers `app/core/deps.py:36` (`if sub is None: raise credentials_exception`)
   - Helper `_no_sub_token()` generates a valid-signature JWT with only `{"exp": ...}` — no `sub` key

3. `tests/test_currencies.py` — three exchange-rate filter tests
   - `test_exchange_rates_no_filter_returns_all` — exercises the no-filter path
   - `test_exchange_rates_filtered_by_from_currency_id` — exercises `currency_service.py:45`
   - `test_exchange_rates_filtered_by_effective_date` — exercises `currency_service.py:49`

**CI changes**:

`.github/workflows/ci.yml` pytest step updated:
```yaml
run: uv run pytest -v --tb=short --cov=app --cov-report=term-missing --cov-report=xml

- name: Upload coverage to Codecov
  uses: codecov/codecov-action@v4
  with:
    token: ${{ secrets.CODECOV_TOKEN }}
    files: ./coverage.xml
    fail_ci_if_error: false
```

**Design note — why `--cov-report=xml` only in CI, not in `addopts`**:
`addopts` in `pyproject.toml` applies to every `uv run pytest` invocation, including local dev.
`coverage.xml` is a machine-readable artifact consumed by Codecov, not useful locally.
Generating it on every local run adds noise and produces a file that must be gitignored.
Keeping it CI-only is the clean separation.

**README**:
```markdown
[![CI](https://github.com/ikuko-otani/payment-ledger-api/actions/workflows/ci.yml/badge.svg)](...)
[![codecov](https://codecov.io/gh/ikuko-otani/payment-ledger-api/graph/badge.svg)](...)
```

**Coverage result**:

| Metric | S6-2 baseline | S6-3 result |
|--------|--------------|-------------|
| Overall coverage | 90.29% | 91.46% |
| Tests passing | 96 | 101 |
| Threshold | 85% | 85% (unchanged) |

---

## TD-013 Re-evaluation

A key pre-work step in S6-3 was distinguishing genuine gaps from TD-013 false negatives
before writing any tests. Without this step, several tests would have been written
for paths that are already executed at runtime.

| Module | Missing lines (S6-2) | Verdict | Action taken |
|--------|---------------------|---------|--------------|
| `auth.py` 23–30 | `user = ...` after `await db.execute` | TD-013 | No new test |
| `user_service.py` 28–36 | `create_user` happy path continuation | TD-013 | No new test |
| `currency_service.py` 22, 33–34 | `return` / `flush` after `await` | TD-013 | No new test |
| `transaction_service.py` 56–92 | entire non-USD conversion body | TD-013 | No new test |
| `deps.py` 41–46 | `user_result.scalar_one_or_none()` | TD-013 (partial) | No new test |
| `deps.py` 36 | `if sub is None` | **Genuine gap** | ✅ New test added |
| `main.py` 38 | `/health` response line | **Genuine gap** | ✅ New test added |
| `currency_service.py` 43–51 | filter branches | **Genuine gap** | ✅ Partial (47 still missed) |
| `deps.py` 66 | `require_auditor_or_admin` 403 | Dead code | No test (UserRole has only ADMIN/AUDITOR) |

`currency_service.py:47` (the `to_currency_id` filter branch) was not tested this goal.
Line 51 (`return list(...)`) is a TD-013 false negative.
Both are below the 85% threshold impact zone — acceptable.

---

## Codecov Setup

1. Sign up at codecov.io with GitHub OAuth
2. Enable the repository in Codecov dashboard
3. Copy `CODECOV_TOKEN` from Settings → General
4. Add as GitHub Actions secret: Settings → Secrets → `CODECOV_TOKEN`
5. Badge becomes active after the first successful CI run post-merge

`fail_ci_if_error: false` on the Codecov action prevents transient upload
failures (network issues, Codecov outages) from breaking the CI pipeline.

---

## Key Takeaways

### What did I learn?

I learned that before writing new tests to improve coverage, it is worth re-evaluating
which gaps are genuine vs. TD-013 false negatives. In S6-3, most of the S6-2 "missing"
lines turned out to be TD-013 — the real gaps were only three areas: the `/health`
endpoint, the `sub=None` JWT path, and the exchange-rate filter branches.

I also learned the full Codecov integration flow end-to-end: generating `coverage.xml`
in CI, uploading via `codecov/codecov-action@v4`, adding the repository secret, and
embedding the badge URL in README. The badge is only activated after the first successful
upload, which happens post-merge (not at PR creation time).

I learned to separate `--cov-report=xml` (CI-only, machine-readable) from
`--cov-report=term-missing` (always-on via `addopts`, human-readable). Mixing them in
`addopts` would clutter local dev runs with an artifact that has no local use.

### What would I do differently?

I would run `git ls-files .coverage coverage.xml` at the start of the goal to check
whether coverage artifacts were accidentally tracked. Discovering `.coverage` and
`coverage.xml` were both tracked required an extra `git rm --cached` step mid-goal.
A pre-flight check would have caught this before the scaffold commit.

### What surprised me?

The TD-013 re-evaluation showed that `app/services/transaction_service.py` (79% reported)
was actually well-covered — the entire `_get_converted_amount_usd` function body after
the first `await` was mis-reported as missed, even though the existing
`test_currency_conversion.py` tests exercised every error path. The reported 79% was
almost entirely a measurement artifact, not a real gap.

I was also surprised that `deps.py:36` (`if sub is None`) had no existing test.
The other JWT edge cases (expired, wrong signature, nonexistent user, inactive user)
were all covered, but the specific case of a token missing the `sub` key entirely
had been overlooked in every prior goal. It is the most basic malformed-token case.

### What is worth remembering for future goals?

1. **TD-013 identification protocol**: before writing tests for `async` functions,
   check whether `await X` is covered but the next line is not. If yes, it is almost
   certainly TD-013. Verify by running the existing test and checking whether the
   endpoint returns the expected status code — if it does, the line executed.

2. **`git ls-files <artifact>` pre-flight**: run this at the start of any goal that
   generates build artifacts. Tracked artifacts that belong in `.gitignore` are a
   common noise source and harder to clean up after they accumulate.

3. **Codecov badge activation timing**: the badge URL is valid immediately, but shows
   "no coverage" until the first upload. This is expected and not a setup error.
   Communicate this to anyone reviewing the README before the first CI run post-merge.

4. **`fail_ci_if_error: false` on upload steps**: coverage upload is a reporting step,
   not a correctness check. Failing the entire CI pipeline because of a Codecov outage
   would block deployments unnecessarily. Keep upload steps non-fatal.
