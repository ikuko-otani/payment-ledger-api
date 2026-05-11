# ADR-002: Adopt Claude Code with Pair-Programming Mode

## Status

Accepted — adopted on 2026-05-11 as the primary implementation-support tool
for this portfolio project.

## Context

Sprint S2 development used Perplexity Spaces with a learning-instruction-based
workflow. Three recurring friction points emerged:

1. **Scaffold inconsistency across Goals** — Perplexity's GitHub integration
   fetches individual files rather than reading the full repository state.
   Step B (scaffold creation) produced files that were occasionally inconsistent
   with the rest of the codebase.
2. **Indirect feedback loop** — Reviewing and applying generated code required
   copy-paste round-trips; there was no direct in-repository execution or file
   editing.
3. **No persistent working rules** — Each session required re-supplying context
   about conventions, layer boundaries, and test patterns.

## Decision

1. Adopt **Claude Code** as the primary implementation-support tool for all
   in-repository work.
2. Retain **Claude.ai Chat (Project)** in a supporting role: Sprint planning,
   retrospectives, and strategic discussion.
3. Restrict **Perplexity** to out-of-code research (technology surveys,
   migration strategy, etc.).
4. Place `CLAUDE.md` in the repository root as the persistent working-rules
   file, read automatically on startup.
5. Operate Claude Code in **pair-programming partner mode** (not code-generator
   mode):
   - No file modifications without explicit instruction.
   - Every code block is classified as ✍️ (type yourself), 🔧 (fill-in
     skeleton), or 📋 (copy-paste OK).
   - Engagement level is controlled by `support_level`:
     `guided` / `balanced` / `stretch`.
6. Formalise the **Step A → B → C Goal execution workflow**
   (scope confirmation → scaffold → walkthrough).
7. Designate `docs/tech-debt.md` as the single source of truth for outstanding
   debt, with immediate registration on discovery.
8. Create `docs/learning-notes/` to make the learning process searchable within
   the repository.

## Rationale

| Factor | Perplexity Spaces | Claude.ai Chat only | Claude Code |
|--------|------------------|---------------------|-------------|
| Full repository awareness | ✗ (file-by-file) | △ (MCP, similar risk) | ✓ (reads entire tree) |
| Direct file editing | ✗ | ✗ | ✓ |
| Persistent working rules | ✗ (re-supplied each session) | △ (Project instructions) | ✓ (CLAUDE.md) |
| Local test / migration execution | ✗ | ✗ | ✓ |
| Pair-programming pedagogy | △ | ✓ | ✓ |
| Sprint planning / strategy | ✓ | ✓ | △ (not its strength) |

Claude Code is the only option that satisfies full-repository awareness and
direct file editing simultaneously — the two properties that caused the most
friction in prior sprints.

## Consequences

### Positive

- Scaffold generation is consistent with the full repository state.
- Feedback loop is direct: file edits, test runs, and Alembic migrations happen
  in the same terminal session.
- The learning process is persisted in `docs/learning-notes/` as a searchable
  knowledge base.
- ADR / tech-debt / troubleshooting / learning-notes documentation culture is
  integrated into the Claude Code working rules.

### Negative / Risks

- Claude Code has no thread-browsing UI; past conversations are not searchable.
  Mitigation: Step C walkthroughs are saved to `docs/learning-notes/`.
- Claude Code shares the Pro plan's 5-hour usage window with Claude.ai Chat.
  Mitigation: Reserve Claude.ai Chat for planning and retrospectives; use Claude
  Code only during active coding sessions.
- `CLAUDE.md` and `flagship-goal-prompt-template.md` have some overlapping
  content; consolidation is a future task.

### Incidental findings (technical debt discovered during this ADR's drafting)

- **TD-007** — `ARCHITECTURE.md` / `docs/adr/` numbering inconsistency
- **TD-008** — Repository layer not separated from service layer
- **TD-009** — Root `/main.py` is a `uv init` leftover
- **TD-010** — `.gitignore` is sparse

All four are registered in `docs/tech-debt.md`.

## References

- `CLAUDE.md` (this repository) — Claude Code working rules
- `docs/tech-debt.md` — TD-007 through TD-010, discovered during this ADR's
  drafting process
- `docs/adr/001-redis-for-idempotency-key.md` — sibling ADR demonstrating the
  same format
