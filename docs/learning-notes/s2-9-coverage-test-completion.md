# S2-9: カバレッジ計測 + テスト補完（20件到達）

**Date**: 2026-05-17
**Goal**: Measure coverage with `pytest --cov=app`; reach TOTAL 60%+ and 20+ collected tests
**Branch**: none — DONE condition already met
**Support level**: balanced

---

## Outcome

No new code was written. Running `uv run pytest --cov=app --cov-report=term-missing tests/`
before starting implementation showed both conditions already satisfied:

```
TOTAL   298   17   94%
29 passed, 1 warning in 61.87s
```

| Condition | Target | Actual |
|-----------|--------|--------|
| Coverage (TOTAL) | 60%+ | **94%** |
| Collected tests | 20+ | **29** |

### Notes on `pytest-cov` installation

`pytest-cov` was not listed in `pyproject.toml` dev dependencies. It was added
before running the coverage check:

```bash
uv add --dev pytest-cov
```

### Coverage detail

| File | Cover |
|------|-------|
| `app\db\session.py` | 42% (lowest — not hit by tests directly) |
| `app\api\v1\routes\accounts.py` | 82% |
| `app\main.py` | 88% |
| All other files | 95–100% |

The uncovered lines in `app\db\session.py` (lines 27–33) are the production
`get_db` dependency — overridden by testcontainer fixtures in all tests, so never
executed by the test suite. This is expected and not a gap worth filling.

---

## Key Takeaways

**What did I learn?**

I learned that `pytest-cov` is a separate package from `pytest` and must be added
explicitly (`uv add --dev pytest-cov`) before `--cov` flags are recognised.

I also learned that low coverage on `app\db\session.py` is expected: the production
`get_db` function is replaced by a test fixture override, so its lines are never
reached during testing. A coverage gap on dependency-injection plumbing is a known
and acceptable pattern, not a sign of missing tests.

**What would I do differently?**

I would add `pytest-cov` to `pyproject.toml` dev dependencies when the test
infrastructure is first set up, so coverage is always available without a separate
install step.

**What surprised me?**

That three goals in a row (S2-7, S2-8, S2-9) all had their DONE conditions met
before any implementation started. The sprint plan was written before the codebase
reached its current state; running a quick check first has become the most
time-efficient first action for any test/coverage goal.

**What is worth remembering for future goals?**

- Add `pytest-cov` to dev dependencies at project setup — it is needed any time
  coverage is a DONE condition.
- Low coverage on DI plumbing (`get_db`, `get_redis`) is expected: those paths are
  overridden by fixtures and not reachable in the test suite.
- For goals whose DONE condition involves test counts or coverage percentages,
  always run the check command first before writing anything.
