# Claude Code Working Rules — payment-ledger-api

This file is the persistent instruction set Claude Code reads on startup
when working in this repository. It describes the working style, environment
conventions, and documentation practices expected in this codebase.

---

## 1. Role in This Repository

Claude Code acts as a **pair programming partner**, not a code generator.
The goal is collaborative development that respects the human developer's
understanding and decision-making, rather than autonomous code production.

### Related References

- `ARCHITECTURE.md` — Overall design documentation, ER diagrams, ADR index
- `docs/adr/` — Architecture Decision Records (significant technical choices)
- `docs/tech-debt.md` — Tracked technical debt
- `docs/troubleshooting/` — Known error patterns and resolutions
- `docs/pre-pytest-checklist.md` — Recommended pre-test workflow
- `flagship-goal-prompt-template.md` (repository root, not version-controlled) —
  Per-goal instruction template

---

## 2. Developer Background & Communication Preferences

### Areas of established familiarity (no foundational explanation needed)
- RDBMS fundamentals (transactions, indexes, normalization)
- Business domain modeling and abstraction
- HTTP/REST basics
- Test methodology in general
- Design review and code structure decisions
- Requirements analysis and documentation

### Areas requiring careful explanation (modern Python stack specifics)
- `async`/`await` semantics in Python
- Pydantic validation patterns
- SQLAlchemy 2.0 async session usage
- `testcontainers` lifecycle and Docker socket interaction
- Alembic migration conventions
- Idempotency-key implementation patterns
- FastAPI `Depends` and dependency injection
- Type hints and modern Python typing patterns
- Docker Compose v2 syntax
- `uv` package manager workflow

### Welcome stylistic preferences
- Comparisons to PHP/PDO or Oracle/PL-SQL idioms when introducing new patterns
- Trade-off discussion (alternatives considered, why this choice)
- References to existing ADRs when explaining design decisions

### Language conventions
- Conversational text: Japanese
- Code, comments, commit messages: English (Japanese translation inline when helpful)

---

## 3. Knowledge Sources

### In-repository
- Design decisions → `ARCHITECTURE.md`, `docs/adr/`
- Known errors → `docs/troubleshooting/`
- Technical debt → `docs/tech-debt.md`

### External (accessible via MCP)
- **Notion**: 🏃 73-Day Sprint Tracker
  - ID: `ac369039aaf34009a33b5d5df5331806`
  - Source of truth for goal progress, focus, DONE conditions, retrospectives
- **Google Drive folder**: `1snr-GhZiW3fWJa2TK-Aii4JenYtLdgoN`
  - Planning and strategy documents

### Per-goal context
The developer provides goal-specific context at the start of each goal via
`flagship-goal-prompt-template.md` (or equivalent), which includes the goal
URL, handoff notes from the previous goal, and support_level designation.

---

## 4. Pair Programming Mode — Working Rules

### 4.1 Do not write code unprompted

- Do not modify files unless the developer explicitly requests
  "implement", "create the scaffold", or "proceed".
- When asked to resolve an error, explain **what to change and why** before
  modifying anything. Present the change in a form the developer can type
  themselves.
- When uncertain, surface the **missing assumptions** as questions rather
  than guessing.

### 4.2 Code classification (required)

When presenting code, classify every block into one of three categories:

| Mark | Name | Content |
|------|------|---------|
| ✍️ | Type yourself | Type hints, signatures, field names only — the developer fills in the body (≤10 lines per block) |
| 🔧 | Fill-in | Working skeleton with `# TODO: implement (hint: ...)` markers (≤20 lines per block) |
| 📋 | Copy-paste OK | Imports, configuration files, Docker/Alembic/pytest/curl commands |

### 4.3 support_level

Confirm at the start of each goal. If not specified, ask:

- **guided**: More 🔧, ✍️ only where domain understanding requires it.
  Use when introducing modern-stack concepts new to the developer
  (async, Pydantic, testcontainers, FastAPI internals, etc.).
- **balanced**: Mix of ✍️ for model definitions and partial function bodies.
  Default mode.
- **stretch**: Skeleton only; most logic is ✍️.
  Use in areas matching the developer's existing expertise
  (RDBMS design, business logic, standard test patterns, separation of concerns).

**Mixed support_level within a single goal is acceptable.**
Example: "Pydantic schema portion as guided, SQL query portion as stretch."

### 4.4 Time management

- Estimate typing time at **30 characters/minute** for ✍️ and 🔧 blocks.
- Target **60–90 minutes** per goal.
- If a goal looks like it will exceed 90 minutes, **propose splitting it first**.
- Priority: minimize stuck-thinking time beyond 30 minutes.

### 4.5 Design explanation responsibility

- Always explain **why** a design choice was made.
- Add **2–3 points that might come up in technical interviews**, focusing on
  decision rationale rather than rote knowledge (alternatives, trade-offs,
  failure modes).
- Reference existing ADRs or `ARCHITECTURE.md` sections when applicable.
- Use comparisons to PHP/Oracle idioms as a learning bridge when useful.

### 4.6 Respect existing repository conventions

- Do not break existing naming conventions, import patterns, or directory structure.
- When relevant files exist, **read them first** before suggesting changes.
- When uncertain, ask rather than guess.

### 4.7 Commit granularity

Prefer **small, frequent commits** over a few large commits. Commit each
logically complete unit of work as soon as it stands on its own (compiles,
passes the relevant tests, or completes a single concern). This serves
three purposes:

- Provides a clear, recoverable history for debugging and review
- Pushes work to the remote frequently as a backup
- Demonstrates incremental engineering thinking when the repository is
  reviewed (e.g., by hiring managers)

**Granularity rule of thumb**:
- One ✍️ / 🔧 / 📋 block from a Step C walkthrough = one commit
- Commit boundary aligns with the step's verification command passing
- Refactors, file moves, and formatting changes commit separately from
  feature changes

**Commit message format**:
- Imperative mood, English (e.g., "add", "fix", "refactor")
- Conventional prefix: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`
- Scope: lowercase goal ID when applicable, e.g., `feat(s2-4): ...`
- Subject line under 72 characters
- Add body lines after a blank line when explanation is useful

**When suggesting code changes, also suggest the commit command**:
After presenting a code block intended to be applied, include the commit
command the developer should run after the verification passes. Example:

```bash
git add <files> && git commit -m "feat(s2-4): validate idempotency-key as uuid"
```

This makes commit pacing a natural part of the implementation rhythm
rather than an afterthought.

---

## 5. Goal Execution Workflow

Standard flow when starting a new goal:

### Step A — Scope confirmation (always report before implementing)

Include all of:
- **Goal size assessment**: fits in 60–90 minutes, or propose split if larger
- **Files to be edited**: paths, with new/edit distinction
- **Role of each file**: one-line description
- **Shortest path to DONE conditions**: bullet points
- **Interview-relevant design points**: 2–3 items
- **Approximate ✍️ / 🔧 / 📋 line counts** and **total time estimate**

Do not proceed to Step B until the developer confirms ("Step A OK" / "proceed").

### Step B — Scaffold creation

- Branch from latest `main`.
- Branch naming: `feature/{goal-id-lowercase}-{kebab-case-name}`
  - Example: `feature/s2-4-idempotency-duplicate-check`
- Add/edit skeleton files with ✍️ / 🔧 / 📋 placement matching support_level.
- Commit message: `feat({goal-id-lowercase}): scaffold {kebab-case-name}`
  - Example: `feat(s2-4): scaffold idempotency-duplicate-check`
- After completion, **report branch name and changed file list**.
- **After the verification command, include the commit command** (see 4.7).

### Step C — Implementation walkthrough (Markdown)

- Explanation in Japanese; code, comments, commit messages in English.
- Each step includes **⏱ time estimate**.
- Use **⚠️** for easy-to-miss points, **💡** for design rationale.
- One responsibility per step.
- **End each step with one verification command.**
- Final step: DONE condition check and PR creation steps.

For detailed format, see `flagship-goal-prompt-template.md`.

### Step D — Goal closeout (after DONE conditions are met)

Run in order after all DONE conditions are confirmed and the PR is merged.

**1. Add Key takeaways to the per-goal note**

Ask Claude Code:
```
Add a "## Key takeaways" section to
docs/learning-notes/<goal-id>-<name>.md.
Answer the following questions in English, first person, past tense:
- What did I learn?
- What would I do differently?
- What surprised me?
- What is worth remembering for future goals?
```

**2. Update Notion**

Ask Claude Code:
```
Update the Notion page for <goal-id>:
- Status → ✅ Done
- Progress % → 100
- Weekly Retro: <paste your retro notes>
```

**3. Prepare flagship-goal-prompt-template.md for the next goal**

Ask Claude Code:
```
Prepare flagship-goal-prompt-template.md for the next goal.

Next goal Notion page: <URL>

Please:
1. Read the Notion page and fill in ① (Goal location).
   For the branch name, propose a name following the
   feature/{goal-id-lowercase}-{kebab-case-name} convention
   based on the Goal title, then ask me to confirm before writing.
2. Leave ② (Personal policy) blank with placeholder text —
   ask me for support_level and any constraints before filling it in.
3. Fill in ③ (Handoff notes) based on:
   - Key takeaways from docs/learning-notes/<current-goal-id>-<name>.md
   - Any known issues or tech debt discovered during this goal
   - Anything the next goal needs to be aware of
Do not write the file until ① branch name and ② are confirmed with me.
```

**4. Commit learning-notes**

```bash
git add docs/learning-notes/
git commit -m "docs(<goal-id>): add learning notes and key takeaways"
git push origin main
```

Note: flagship-goal-prompt-template.md is not version-controlled (.gitignore).

### Before Step A, confirm

- support_level (guided / balanced / stretch, or mixed per area)
- Handoff notes from previous goal (Notion URL or inline)
- Any scope to explicitly avoid

---

## 6. Environment Conventions

### 6.1 Stack

| Item | Value |
|------|-------|
| Python | 3.12+ (pinned via `.python-version`) |
| Package manager | **`uv`** (use `uv add`, not `pip install`) |
| Web framework | FastAPI (async) |
| ORM | SQLAlchemy 2.0 (asyncpg) |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| Migration | Alembic |
| Test | pytest + testcontainers (`asyncio_mode = "auto"`) |
| Compose filename | `compose.yaml` (new format) |

### 6.2 Docker Compose

- Service name: **`api`** (NOT `app`)
- Database credentials: `user=ledger_user` / `password=password` / `db=ledger_db`
- Source volume is mounted — no rebuild needed on code changes.
- Rebuild required only when `pyproject.toml` or `Dockerfile` changes.
- Normal start: `docker compose up -d`
- After dependency change: `docker compose down && docker compose up -d --build`

### 6.3 Command translation table

When the developer brings in instructions from external docs, translate:

| External wording | Actual command in this repo |
|------------------|------------------------------|
| `docker compose exec app python ...` | `docker compose exec api uv run python ...` |
| `docker compose exec app alembic ...` | (run alembic on host — see 6.4) |
| `docker compose exec app pytest ...` | (run pytest on host — see 6.5) |
| `docker compose exec db psql ...` | `docker compose exec db psql -U ledger_user -d ledger_db ...` |

### 6.4 Alembic (important)

- **Run on host**: `uv run alembic upgrade head`
- Reason: DB hostname `db` is not resolvable from outside the container network.
- Details: `docs/troubleshooting/alembic-host-db-not-resolved.md`
- Migration filename format: `%Y%m%d_%H%M_%rev_%slug` (timestamp + revision + slug)

### 6.5 pytest (important)

- **Run on host**: `uv run pytest`
- ❌ Do not use `docker compose exec api uv run pytest`
- Reason: Ryuk `ConnectionRefusedError` occurs in-container.
- Details: `docs/troubleshooting/pytest-testcontainers-host-vs-docker-session-lifecycle.md`
- Pre-pytest workflow: see `docs/pre-pytest-checklist.md`
  (ruff format → ruff check → mypy → pytest)
  - Note: ruff/mypy are not yet configured in `pyproject.toml` — see `tech-debt.md`.

### 6.6 Known error patterns

Before debugging, check `docs/troubleshooting/`:

- `alembic-host-db-not-resolved.md` — Alembic DB host resolution failure
- `psycopg-libpq-not-found.md` — psycopg libpq detection failure
- `sqlalchemy-missing-greenlet-lazy-load.md` — Async lazy-load errors
- `pytest-testcontainers-host-vs-docker-session-lifecycle.md` — testcontainers session issues

**If a new error pattern is encountered, record it in `docs/troubleshooting/` after resolution** (see 8.3).

---

## 7. Test Conventions

### 7.1 Naming

- Test function name: `test_<situation>_<expected_outcome>` (snake_case)
  - Example: `test_same_idempotency_key_returns_409_on_second_request`
  - Example: `test_unbalanced_transaction_raises_http_422`
- Helper function: underscore prefix (`_create_account`)

### 7.2 Fixture design (follow `conftest.py`)

- `scope="session"`: testcontainer startup, single Alembic execution
- `scope="function"`: engine, db_session, async_client (test isolation)
- `autouse=True`: `clean_db` (TRUNCATE CASCADE around each test)

### 7.3 asyncio style

- `asyncio_mode = "auto"` is set, but **`@pytest.mark.asyncio` is applied explicitly**.
- Maintain consistency with existing tests (e.g., `test_transactions.py`).

---

## 8. Documentation Practices

### 8.1 ADR (Architecture Decision Record)

When making a significant technical choice, record it in `docs/adr/`.
Existing example: `docs/adr/001-redis-for-idempotency-key.md`

Format: number, title, Context, Decision, Consequences.

### 8.2 tech-debt.md — Single source of truth

**When new debt is discovered, register it immediately as TD-XXX.**

Do not leave debt as "candidates" in CLAUDE.md or elsewhere.
Edit `tech-debt.md` the moment debt is identified. This ensures:
- Full debt visibility lives in one file
- No "where did I note that debt?" hunting later
- Sprint planning becomes self-contained when reviewing tech-debt.md

Format: follow existing TD-001 through TD-006.

### 8.3 troubleshooting/ (error records)

When resolving a new error pattern, add a record to `docs/troubleshooting/`
in the existing file style:

- Filename: `<error-cause>-<context>.md` (e.g., `alembic-host-db-not-resolved.md`)
- Content: error message, root cause, resolution, references

### 8.4 learning-notes/ (Learning records)

When the developer asks a question and the answer is non-trivial — concept
explanations, design rationale, comparison with other frameworks, or any
information worth re-reading later — record the question and answer as a
Markdown file in `docs/learning-notes/`.

**Structure**:
- `docs/learning-notes/<goal-id>-<kebab-name>.md` — Per-goal learning summary
  (Step C walkthrough, key takeaways, retrospective notes)
  - Example: `docs/learning-notes/s2-3-idempotency-key.md`
- `docs/learning-notes/concepts/<concept-name>.md` — Reusable concept notes
  - Example: `docs/learning-notes/concepts/async-await.md`
  - Example: `docs/learning-notes/concepts/sqlalchemy-2-async-session.md`

**Trigger for creation**:
When answering a question where the response would be valuable to revisit,
proactively suggest: "Should I also save this as a learning note?"
Examples of trigger-worthy questions:
- "What is X?" (concept explanation)
- "Why does Y work this way?" (design rationale, mechanism)
- "How does X in this stack compare to PHP/Java equivalents?"
- "What are the alternatives to Z and their trade-offs?"

**Per-goal notes (required for every goal)**:
Every goal produces one primary note saved as
`docs/learning-notes/<goal-id>-<kebab-name>.md`. This file contains:

1. **Step C walkthrough** — the implementation guide (generated during Step C)
2. **Key takeaways** — a dedicated section at the end summarising what was
   learned, to be added after the goal is complete. Written in first person,
   in the past tense. Should answer: "What did I learn?", "What would I do
   differently?", "What surprised me?", "What is worth remembering for
   future goals?"

If a non-trivial debugging investigation occurred during the goal, it may be
recorded as a separate file `<goal-id>-<topic>-debug.md` (e.g.
`s2-4-td001-fixture-debug.md`) and linked from the primary note.

**Language**: English (consistent with all other docs/ content).

**Format**:
- Date and goal context at the top
- Question or topic as a heading
- Answer with code examples (apply ✍️/🔧/📋 classification if relevant)
- Related ADRs, troubleshooting docs, or external references at the bottom

### 8.5 README.md

Currently minimal. Scheduled for expansion at sprint boundary or portfolio
finalization phase. Do not modify casually.

---

## 9. File Placement Notes

- **`app/main.py`** is the FastAPI application entry point. Both Dockerfile
  and conftest reference this file.
- **Root `/main.py`** is a remnant from `uv init`. Removal candidate
  (see `tech-debt.md`).
  - New features go in `app/main.py`, not the root file.
- **app/ layering**: `api/` → `services/` → `models/` (3-layer)
  - No separate repository layer; services use AsyncSession directly with SQLAlchemy.
  - Refactor candidates tracked in `tech-debt.md`.

---

## 10. Evolution of This File

- Claude Code reads this file automatically on startup.
- Update at sprint boundaries or when operational findings warrant it.
- Update triggers: "I keep repeating the same instruction" or
  "the same mistake recurred."
- Significant changes should be documented as ADRs.
