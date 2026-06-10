# Workflows

Workflow rules for AI coding agents.

This file defines task selection, execution, review, validation, and worktree
safety. Treat it as required context for every task.

## Core Rule

Always classify the task before acting.

If the task type is unclear, inspect the repository context first. Ask the user
only when the answer changes the design, validation obligation, or edited file
set.

## Workflow Selection

Use `Small Local Change` when all are true:

- the change is limited to one file or one tightly bounded module
- the behavior is already clear
- no architecture boundary changes
- no app wiring, config, queue, outbox, repository, adapter, or model changes
- no cross-layer test work

Use `Standard Change` when any are true:

- the change touches multiple files in one layer
- the change affects tests, stubs, docs, or app calls
- the blast radius is clear but larger than a tiny edit
- the work needs a short plan and acceptance criteria

Use `Multi-Agent Change` when any are true:

- the change touches more than one layer
- the change changes models, repositories, adapters, workers, queues, outbox,
  app wiring, config, or architecture
- the request contains many tasks
- independent review would reduce risk
- the user asks for a broad implementation or refactor

Use `Ideation And Design` when any are true:

- the user asks how something could be implemented
- the user asks for options, tradeoffs, architecture, or design help
- the user appears to want collaborative exploration before code
- external research or independent exploration would improve the solution

## Required Context

Always follow the loading rules in `AGENTS.md`.

For code and architecture work, load `docs/architecture.md` before planning.
For tests, test scaffolding, or test documentation, load `docs/tests.md` before
planning. For documentation edits, read the target documents before editing.

## Worktree Safety

Before editing any file, inspect the worktree state.

Treat uncommitted changes as user-owned unless the current task created them.

Never overwrite, revert, delete, or reformat user-owned changes unless the user
explicitly requests that exact operation.

If dirty changes are unrelated, ignore them. If dirty changes overlap the
target files, inspect them and preserve them. If preserving them is unsafe or
impossible, stop and ask the user.

Never run destructive commands such as `git reset --hard`, `git checkout --`,
`git clean`, or broad deletion commands unless the user explicitly requests the
exact destructive action.

## Planning

Create a plan for `Standard Change` and `Multi-Agent Change`.

Plans must be short, sequential, and tied to acceptance criteria.

Use this shape:

```text
1. Add service port
   Acceptance criteria:
   - protocol exists in `src/application/ports.py`
   - use cases depend on the protocol, not infrastructure
   - `python3 -m compileall src` passes
```

Skip a plan only for `Small Local Change`.

## Small Local Change

Use this workflow for tiny, obvious, localized edits.

Steps:

1. Load required context from `AGENTS.md`.
2. Read the target file and any directly related test or doc.
3. Inspect the worktree before editing.
4. Make the smallest correct edit.
5. Run the smallest relevant validation.
6. Perform a lightweight self-review.
7. Report the change and validation.

Lightweight self-review must check:

- diff is scoped to the request
- no unrelated refactor was introduced
- names follow `docs/rules.md`
- architecture boundaries were not crossed
- validation passed or failure is clearly reported

## Standard Change

Use this workflow for bounded implementation or documentation work that does
not require the full multi-agent loop.

Steps:

1. Load required context from `AGENTS.md`.
2. Read relevant source, tests, and docs directly.
3. Inspect the worktree before editing.
4. Create a short sequential plan with acceptance criteria.
5. Execute one task at a time.
6. Validate after code or test changes.
7. Re-read changed docs when documentation changed.
8. Review the final diff against acceptance criteria.
9. Report changes, validation, and remaining risks.

Preferred implementation order:

```text
models and config
db/session plumbing
repositories
unit of work
application use cases
external-client adapters
entrypoints
docs
```

## Multi-Agent Change

Use this workflow for broad, risky, or multi-layer changes.

The required roles are:

- Orchestrator
- Coder
- Reviewer

If subagents are available, use one Orchestrator in the main thread, one Coder
agent, and one Reviewer agent. If subagents are unavailable, simulate the roles
sequentially in the main thread. Preserve the same handoff and review loop.

### Orchestrator

The Orchestrator owns execution order, task boundaries, and acceptance criteria.

The Orchestrator must:

1. Load required context from `AGENTS.md`.
2. Inspect relevant files and tests.
3. Inspect the worktree before any edit.
4. Define the task list.
5. Define global acceptance criteria.
6. Hand one task at a time to the Coder.
7. Include relevant context, constraints, files, and acceptance criteria in each
   handoff.
8. Send completed Coder work to the Reviewer.
9. If Reviewer rejects, return the findings to Coder.
10. If Reviewer accepts, continue with the next task.
11. Continue until all tasks are accepted and global acceptance criteria are met.
12. Run final validation.
13. Report the result.

### Coder

The Coder owns the implementation for one task at a time.

The Coder must:

- use the provided handoff as the scope boundary
- inspect only the relevant files unless more context is required
- make minimal diffs
- preserve short names when clear
- avoid unrelated refactors
- avoid hidden behavior in stubs
- return changed files, reasoning summary, and validation performed

If Reviewer rejects the task, the Coder must address the concrete findings and
return the revised work for another review.

### Reviewer

The Reviewer owns independent acceptance checking.

The Reviewer must check:

- the task acceptance criteria
- `docs/rules.md`
- `docs/workflows.md`
- `docs/architecture.md` when architecture or code is involved
- `docs/tests.md` when tests are involved
- architecture boundaries
- hidden behavior, missing stubs, or incorrect dependencies
- validation evidence

Reviewer output must be either `accepted` or `rejected`.

Reject only for correctness gaps, missing acceptance criteria, architecture
drift, missing validation, or behavior that conflicts with required docs. Do not
reject for style preference alone.

Rejected findings must include concrete file and line references when possible.

## Ideation And Design

Use this workflow when the user asks for help designing a solution rather than
direct implementation.

Steps:

1. Load required context from `AGENTS.md`.
2. Inspect relevant local files with tools.
3. Use subagents for read-heavy exploration when they reduce context load.
4. Search the web when current external facts, libraries, APIs, or examples
   could materially improve the design.
5. Separate local facts, external facts, and agent inference.
6. Do not edit code unless the user explicitly asks for implementation.
7. Return a concise recommendation with tradeoffs, implementation order, risks,
   and open questions.

Web search is always allowed in this workflow. Links and citations are optional
unless the user asks for them or precise source attribution materially improves
the answer.

## Validation

Do not mark a task complete until validation passes or the inability to validate
is clearly reported.

After code changes, always run:

```bash
python3 -m compileall src
```

For test changes, also follow `docs/tests.md`.

When app wiring changes and the repository exposes `get_app()`, run:

```bash
uv run python - <<'PY'
from application.app import get_app
app = get_app()
print(app.name, app.version)
PY
```

For config changes, validate settings construction.

For queue, worker, outbox, or persistence changes, validate the local or memory
mode still instantiates unless the task explicitly removes that mode.

If validation fails, report the exact command and summarize the failure. Fix the
failure when it is in scope, then rerun validation.

If validation cannot run because of a missing service or unavailable dependency,
report the blocker and identify which behavior remains unproven.

## Documentation Validation

Documentation-only edits still require a lightweight scan.

After documentation edits:

- re-read the edited sections
- check that referenced files exist
- check that referenced commands, method names, and workflow names are current
- scan for stale references with `rg`
- run the smallest relevant validation command when documentation changed a code
  contract, public method name, or required workflow

Do not claim documentation is synchronized unless this scan was performed.

## Documentation Update Triggers

Update `docs/rules.md` when reusable coding standards change.

Update `docs/workflows.md` when task execution, planning, validation, review,
subagent use, or documentation-update procedure changes.

Update `docs/architecture.md` when repository-specific architecture, model
shape, ports, APIs, outbox semantics, implementation order, or current state
changes.

Update `docs/tests.md` when test strategy, pytest commands, fixture patterns,
or test activation rules change.

Update `AGENTS.md` when bootstrap loading order, document precedence, or default
agent role changes.

If a code change makes any required documentation false, update that
documentation in the same task unless the user explicitly says not to.

## User Alignment

Ask targeted questions only when the answer changes the design.

Good questions include:

- Stub only, or full implementation?
- Domain model, persistence row, API schema, or more than one?
- Exposed through app facade, CLI, API, worker, or internal only?
- Should this dependency become a protocol?
- Should this write through Unit of Work?
- Memory queue, direct call, or durable outbox?
- External-client behavior now, or adapter signatures only?
- What are the failure, retry, and idempotency rules?

When repository context already answers the question, make the reasonable choice
and continue.

## Creating Delivery Plans

Use this workflow when the user asks for a delivery plan, roadmap, milestone
plan, implementation sequence, phased rollout, or asks to rewrite a plan so it
is more delivery-focused.

Delivery plans must describe working milestones, not activity buckets. A phase
is complete only when it ends in a runnable capability that can be exercised
locally through an intended boundary and validated with evidence.

Before creating or rewriting a delivery plan:

- Load the required context from `AGENTS.md`.
- Read `docs/architecture.md` when the plan covers code, app wiring, models,
  repositories, adapters, workers, queues, outbox, entrypoints, or config.
- Read `docs/tests.md` when the plan defines validation, smoke tests,
  notebooks, or test strategy.
- Inspect the current plan file when updating an existing plan.
- Preserve unrelated local changes.

A delivery plan should include:

- the current baseline and known gaps
- a dependency graph when sequencing matters
- one section per delivery milestone
- the working milestone for each delivery
- the capability delivered
- the primary boundary users or developers will exercise
- the implementation slice needed to reach the milestone
- acceptance criteria stated as observable behavior
- validation commands, with `task test` as final evaluation when code changes
  are part of the delivery
- delivery evidence such as tests, smoke checks, notebooks, or docs
- explicit non-scope items and deferred risks

Every delivery milestone must satisfy these rules:

- It must end with behavior that works locally.
- It must be demonstrable through an application, worker, API, CLI, MCP, or
  other intended boundary.
- It must avoid phases that only say "setup", "wiring", "tests", or
  "scaffolding" unless those tasks are part of a larger working milestone.
- It must name the smallest useful capability a developer can run after the
  phase lands.
- It must include deterministic validation that does not require external
  provider credentials unless the milestone is explicitly a provider-backed
  delivery.
- It must keep architecture boundaries intact: application use cases decide,
  repositories persist, adapters translate provider or infrastructure details,
  workers call app boundaries, and entrypoints translate transport concerns.

Prefer delivery names based on working outcomes:

```text
Delivery 1: Local ingest works
Delivery 2: Local retrieval works
Delivery 3: Split-check lifecycle works
Delivery 4: Public local workflows work
Delivery 5: Relevance and provider path works
Delivery 6: Release-ready local workflow
```

Avoid delivery names based only on activities:

```text
Phase 1: Add tests
Phase 2: Wire dependencies
Phase 3: Refactor services
Phase 4: Setup notebooks
```

When rewriting an existing task-heavy plan, preserve useful technical details
but move them under milestone sections as implementation slices, acceptance
criteria, validation, or non-scope. Remove copy-paste prompt boilerplate unless
the user explicitly wants prompts as the artifact.
