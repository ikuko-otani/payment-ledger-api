# ruff format: `--check` fails on Markdown-embedded Python code blocks

## Error

CI `lint` job fails on `uv run ruff format --check .` after a routine
Dependabot bump (`ruff>=0.15.20` constraint resolved to `0.16.x`):

```
unformatted: File would be reformatted
  --> docs/troubleshooting/asyncpg-enum-uppercase.md:18:9
   |
17 | # Migration creates: ENUM ('ADMIN', 'AUDITOR')
   - sa.Enum('ADMIN', 'AUDITOR', name='userrole')
18 + sa.Enum("ADMIN", "AUDITOR", name="userrole")
19 | ```
   |

##[error]Process completed with exit code 1.
```

`ruff check .` (lint) passes; only `ruff format --check .` fails, and the
diffs point at ` ```python ` fenced code blocks inside `docs/` Markdown
files that were never touched by this change.

## Root Cause

Starting with ruff 0.16, `ruff format` formats fenced ` ```python ` code
blocks embedded in Markdown files by default — not just `.py` files. This
is a behavior change, not a config change on our side.

`pyproject.toml` pins `ruff` with an open-ended lower bound
(`ruff>=0.15.20`), so a routine Dependabot version bump silently pulled in
this new formatting scope. Any Markdown doc under `docs/` with a Python
code fence that predates ruff 0.16 (or was hand-edited afterward) can now
fail `ruff format --check .` even though no Python source changed.

## Resolution

Run the formatter and let it rewrite the affected Markdown files, then
commit the result like any other formatting fix:

```bash
uv sync
uv run ruff format .
uv run ruff format --check .   # confirm clean
```

No `pyproject.toml` / `[tool.ruff]` configuration change is needed — this
is expected formatting, not a bug. If Markdown code-block formatting is
ever unwanted, it can be scoped out via `[tool.ruff.format]`
`exclude`, but as of this writing the team has kept it enabled since the
resulting diffs (quote style, blank lines around functions) match the
project's existing Python style.

## References

- Encountered while merging Dependabot PR #126
  (`chore(deps-dev): update ruff requirement from >=0.15.20 to >=0.16.1`)
- Affected files: `docs/troubleshooting/asyncpg-enum-uppercase.md`,
  `docs/troubleshooting/asyncpg-sslmode-not-accepted.md`,
  `docs/troubleshooting/pytest-testcontainers-host-vs-docker-session-lifecycle.md`
- Commit: `style: reformat docs code blocks for ruff 0.16 markdown formatting`
