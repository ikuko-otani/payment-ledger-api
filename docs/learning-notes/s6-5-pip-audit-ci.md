# S6-5: pip-audit CI Step

**Date**: 2026-06-10
**Goal**: S6-5 — Add a pip-audit dependency vulnerability scan to CI
**Branch**: feature/s6-5-pip-audit-ci
**PR**: #58

## Goal Overview

Added `pip-audit` (SCA — Software Composition Analysis) as a dev dependency
and wired it into the existing `lint` job in `ci.yml` as a step (not a
separate job), so that known vulnerabilities in dependencies fail CI.
README now documents this in a new `## CI` section.

A real vulnerability (`idna` 3.13, CVE-2026-45409) was found on the first
local run and resolved as part of this goal.

## What is pip-audit?

`pip-audit` is PyPA's official SCA tool. It checks installed packages (or
`pyproject.toml` / `requirements.txt`) against a vulnerability database and
reports known CVEs/GHSAs with affected and fixed version ranges.

The default data source is **OSV (Open Source Vulnerabilities)** —
`osv.dev`, an aggregator maintained by Google that pulls in the PyPI
Advisory Database and GitHub Security Advisories. `pip-audit` queries
`osv.dev` with each package name + version.

PHP/Composer analogy: `composer audit`, which also queries an OSV-backed
advisory database.

### SAST vs SCA

| | SAST | SCA |
|---|---|---|
| Target | Code you wrote | Dependencies you use |
| Example tools | bandit, Semgrep | pip-audit, Dependabot |
| Detects | Vulnerable code patterns (SQL injection, hardcoded secrets, ...) | Known-CVE package versions |
| In this goal | Out of scope (explicitly excluded) | Implemented |

The two are complementary: SAST can't catch a vulnerability that lives
entirely in a third-party library.

## Implementation

### 1. `pyproject.toml` / `uv.lock` — add pip-audit as dev dependency

```bash
uv add --dev pip-audit
```

Adds `"pip-audit>=2.10.0"` to `[dependency-groups].dev`. Because it's added
via `uv add --dev`, it's also picked up by the `pip` ecosystem in
`dependabot.yml` (S6-4) for future version-bump PRs.

### 2. Resolve the detected vulnerability (idna CVE-2026-45409)

First local run of `uv run pip-audit` reported:

```
Found 1 known vulnerability in 1 package
Name Version ID             Fix Versions
---- ------- -------------- ------------
idna 3.13    CVE-2026-45409 3.15
```

`idna` is a *transitive* dependency (pulled in by `anyio`, `requests`,
`email-validator`, not declared directly in `pyproject.toml`). Since the
existing version constraints from those packages already allow a newer
`idna`, it could be bumped without touching `pyproject.toml`:

```bash
uv lock --upgrade-package idna
uv sync --all-groups
```

This bumped `idna` 3.13 → 3.18, after which `pip-audit` reported
`No known vulnerabilities found`.

💡 If the upgrade had **not** been possible without a breaking change,
the fallback would have been `pip-audit --ignore-vuln <CVE-ID>` plus a
`tech-debt.md` entry recording why and when to revisit — not adding
unrelated scanners.

### 3. `.github/workflows/ci.yml` — add the audit step to the `lint` job

```yaml
      - name: Type check with mypy
        run: uv run mypy --strict app/

      - name: Security audit (pip-audit)
        run: uv run pip-audit
```

Added as a **step** in the existing `lint` job (per the goal's Focus:
"独立した job ではなく step として組み込む"), right after the mypy step.
`uv sync --all-groups` already runs earlier in the same job, so no extra
setup is needed. `pip-audit` exits non-zero on any detected vulnerability,
which fails the step (and the job) automatically — no extra `if`/`exit`
logic required.

Note: Notion's "やること" wrote `run: pip-audit`, but per CLAUDE.md 6.3 this
is a uv project, so the command is `run: uv run pip-audit`.

### 4. `README.md` — document the scan in a new CI section

```markdown
## CI

Every push and pull request runs linting (ruff), type checking (mypy --strict),
the test suite with coverage, and a dependency vulnerability scan (pip-audit).
```

Added directly after `## Badges`, before `## Observability`.

## Knowledge Check (from Notion)

**Q1: Which database does pip-audit reference (OSV / PyPI Advisory, etc.)?**

By default, **OSV (Open Source Vulnerabilities)**, `osv.dev` — an aggregator
covering the PyPI Advisory Database and GitHub Security Advisories.

**Q2: If a known vulnerability can't be fixed immediately, how do you manage CI?**

1. Try `uv lock --upgrade-package <name>` first — often a transitive
   dependency can be bumped within existing constraints with no
   `pyproject.toml` change (this is what happened with `idna` here).
2. If an upgrade isn't possible (breaking change, no fix yet), use
   `pip-audit --ignore-vuln <CVE-ID>` to unblock CI temporarily.
3. Record the ignored CVE in `docs/tech-debt.md` as a TD item with the
   reason and a condition for revisiting it.

**Q3: What is the difference between SAST and SCA?**

SAST analyzes code you wrote for vulnerable patterns (e.g. bandit). SCA
checks the known-vulnerability status of the dependencies you consume
(e.g. pip-audit, Dependabot). This goal implemented SCA only — SAST tools
remain explicitly out of scope per Notion's "やらないこと".

## Key Takeaways

- I learned that `pip-audit` is backed by the OSV database, which
  aggregates PyPI Advisory and GitHub Security Advisory data — the same
  kind of source `composer audit` uses on the PHP side.
- I learned that a transitive-dependency CVE can often be fixed with
  `uv lock --upgrade-package <name>` alone, without editing
  `pyproject.toml` — useful since most CVEs in practice show up in
  packages I never declared directly.
- I was surprised that adding `pip-audit` immediately surfaced a real,
  current CVE (idna 3.13 / CVE-2026-45409) on the very first run —
  it made the "this isn't just a checkbox" value of the tool concrete
  right away.
- For future goals: if `pip-audit` ever finds something that *can't* be
  upgraded cleanly, the `--ignore-vuln` + `tech-debt.md` pairing from Q2
  is the documented escape hatch — reach for that instead of adding
  unrelated suppression mechanisms.

## References

- pip-audit (https://pypi.org/project/pip-audit/)
- OSV database (https://osv.dev)
- CVE-2026-45409 (idna)
