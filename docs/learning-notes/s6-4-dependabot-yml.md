# S6-4: dependabot.yml 設定

**Date**: 2026-06-09
**Goal**: S6-4 — Enable GitHub Dependabot for automated dependency updates
**Branch**: feature/s6-4-dependabot-yml
**PR**: #49

## Goal Overview

Added `.github/dependabot.yml` to enable automated dependency update PRs via
GitHub Dependabot. Covers Python packages (pip ecosystem) and GitHub Actions
workflow dependencies.

## Implementation

### File created: `.github/dependabot.yml`

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
```


### Field Reference

`version: 2`

The only valid schema version for Dependabot configuration.

`package-ecosystem: "pip"` — Why not "uv"?

Dependabot defines ecosystems by how they connect to a package registry,
not by the tool used. Since uv uses PyPI (pip-compatible), pyproject.toml
and `uv.lock` are recognized as the `pip` ecosystem. There is no `uv` ecosystem
value.

PHP analogy: Like Composer using Packagist — the registry is separate from
the tooling.

`directory: "/"`

Path from repository root where the package manifest lives. Use `/` when
`pyproject.toml` is at the root. In a monorepo, use `/packages/mylib`.

`schedule.interval: "weekly"` + `day: "monday"`

- `daily`: creates too many PRs, blocks review queue
- `weekly` (Monday): batches updates for a start-of-week review cycle
- `monthly`: too infrequent for timely security patches

`open-pull-requests-limit: 5`

Default is 5, but explicit configuration documents intent. On first Dependabot
activation, all accumulated version gaps become PRs simultaneously ("PR flood")
— this cap prevents overload.

package-ecosystem: "github-actions"

Monitors `uses:` references in `.github/workflows/*.yml`. Current tracked actions:

- `actions/checkout@v4`
- `astral-sh/setup-uv@v5`
- `codecov/codecov-action@v4`

Supply Chain Security: The `tj-actions/changed-files` incident (March 2025)
demonstrated how compromised Actions can leak secrets. Dependabot PRs for
Actions updates reduce the attack surface by keeping versions current.

GitHub UI Steps

1. Repository Settings → Security → Code security and analysis
2. Enable Dependabot alerts
3. Enable Dependabot security updates

Note: `dependabot.yml` in the repo activates version updates automatically
upon push. Alerts/security updates require separate UI activation.

## Knowledge Check (from Notion)

**Q1: What is the difference between Dependabot and Renovatebot?**

| Feature | Dependabot | Renovatebot |
|---------|-----------|-------------|
| Hosted by | GitHub (native) | Mend.io / self-hostable |
| Config | Simple YAML | Flexible JSON |
| PR grouping | Limited | Highly configurable |
| Monorepo support | Basic | Excellent |

Dependabot is simpler and GitHub-native (zero extra setup); Renovate is more
powerful for complex configurations. For a small API project, Dependabot is
the right choice.

**Q2: What should you do when Dependabot generates too many PRs?**

1. Lower `open-pull-requests-limit` to cap concurrent PRs (done in this goal)
2. Use `ignore` to exclude specific packages from updates
3. Use `groups` to batch multiple package updates into a single PR
4. Switch `interval` to `monthly` to reduce frequency

**Q3: Explain the relationship between Supply Chain Security and SBOM (Software Bill of Materials)**

An SBOM is a complete inventory of all dependencies in a software artifact —
the equivalent of a food ingredient label.

- SBOM = makes **what is included** visible
- Dependabot = continuously monitors and fixes **whether it remains safe**

The SLSA framework treats SBOM generation + automated patch application as
the foundation of Supply Chain Security. Dependabot handles the automated
patch application side.

## Key Takeaways

- Dependabot ecosystems are defined by package registry, not tooling:
uv projects use pip because uv resolves from PyPI
- dependabot.yml activates version updates automatically on push;
Dependabot alerts and security updates require separate GitHub UI activation
- package-ecosystem: "github-actions" monitors Action versions independently
from application dependencies — both are needed for full coverage
- open-pull-requests-limit: 5 default matches our explicit setting;
the value of writing it explicitly is documentation of intent, not behavior change
- Supply Chain Security is a strong interview talking point:
frame dependabot.yml as "structural risk elimination", not just convenience

## References

- Dependabot configuration options (https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file)
- Supported package ecosystems (https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/about-dependabot-version-updates#supported-repositories-and-ecosystems)
