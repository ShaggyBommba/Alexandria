# AGENTS.md

Bootstrap instructions for coding agents.

## Required Context

Before selecting a workflow, planning, or executing any task, load and follow:

- `docs/rules.md`
- `docs/workflows.md`

Before planning or executing code, architecture, model, repository, adapter,
worker, queue, outbox, app wiring, or configuration changes, also load and
follow:

- `docs/architecture.md`

Before planning or executing test changes, test scaffolding, or test
documentation, also load and follow:

- `docs/tests.md`

For documentation-only edits, read the relevant target documents first. For
test documentation, `docs/tests.md` is relevant. For workflow documentation,
`docs/workflows.md` is relevant. For repository-specific architecture
documentation, `docs/architecture.md` is relevant.

If a required file is missing, say which file is missing before planning and
continue with the best available context.

## Document Ownership

Use the documentation files as follows:

- `AGENTS.md` defines bootstrap loading order, document precedence, required
  context, and the default agent role.
- `docs/rules.md` defines reusable coding standards.
- `docs/workflows.md` defines workflow selection, planning, execution,
  validation, review, worktree safety, and documentation-update procedure.
- `docs/architecture.md` defines repository-specific architecture, models,
  ports, APIs, workflows, and current implementation state.
- `docs/tests.md` defines test standards and test workflows.

Do not duplicate detailed workflow procedure in `AGENTS.md`. Put procedural
logic in `docs/workflows.md`.

## Precedence

When documents conflict, use this precedence:

1. `AGENTS.md` for bootstrap behavior and required context.
2. `docs/rules.md` for reusable coding standards.
3. `docs/workflows.md` for task execution procedure.
4. `docs/architecture.md` for repository-specific architecture and current
   implementation state.
5. `docs/tests.md` for test-specific procedure and expectations.

If two documents both apply, prefer the more specific document for the current
task. If a conflict changes implementation behavior or validation obligations,
ask the user before editing.

## Default Role

Act as the Orchestrator Agent by default.

Always:

- preserve architecture while moving work from request to verified result
- explore before planning
- select the workflow from `docs/workflows.md`
- keep diffs scoped
- verify with commands
- report evidence, not impressions

Use subagents when the selected workflow calls for them and they are available.
If subagents are unavailable, simulate the required roles sequentially as
defined in `docs/workflows.md`.

## Final Response

Keep final responses short. Include what changed, validation run, remaining
stubs or risks, and sources used if external research informed the change.
