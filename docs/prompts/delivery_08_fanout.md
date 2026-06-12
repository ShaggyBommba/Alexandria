Role: You are the "Delivery 8 Implementation Agent" for Alexandria. Act as the
Orchestrator Agent and use the Standard Change workflow from `docs/workflows.md`
(bounded change across one application use case, the splitter adapter, config,
and tests). Escalate to Multi-Agent only if scope grows.

Objective: Deliver "Tree Fan-Out Stays Bounded." Make the maximum children per
node, `F`, an explicit, configurable, enforced policy, and prove the tree stays
roughly `F`-ary. Under the documents-on-leaves model a branch gains children
only at split time, so fan-out is bounded structurally; this delivery turns the
hardcoded cap into a policy and proves the invariant. Do not build a
re-clustering mechanism for existing branch children.

Required Context:
Load and follow `AGENTS.md`, `docs/rules.md`, `docs/workflows.md`,
`docs/architecture.md`, and `docs/tests.md` before planning, editing, or
validating. Read the "Epic: Hierarchical Summarization Tree" preamble and the
"Delivery 8" section of `delivery_plan.md`.

Prerequisite: Delivery 7.

Greenfield: nothing is live. No backward-compatibility shims or regression
scaffolds. Worktree Safety: inspect first; unrelated dirty files are user-owned;
edit only what this delivery requires.

Scope (read each before editing):
- `src/infrastructure/config.py` — add `max_children` (default `10`) to the
  split or ingest settings section.
- `src/infrastructure/agents/splitter.py` — replace the hardcoded
  `SplitResult` children `max_length=10` with the configured `F`, and pass `F`
  into the splitter prompt.
- `src/application/usecases/split.py` — `Split.validate` rejects any plan whose
  child count exceeds `F`, before durable writes; on rejection restore the
  source leaf to active through the existing release path.
- `src/application/app.py` — inject `max_children` into `Split` and the
  splitter wiring.
- `tests/application/usecases/test_split.py` — prove over-fan-out rejection.
- `tests/integration/test_fanout_flow.py` — new invariant test.

Behavior Contract:
- `F` is read from settings, not a literal, and injected into `Split` and the
  splitter.
- `Split.validate` rejects a plan with more than `F` children using the existing
  `SplitPlanError`, before any durable mutation. On rejection, the source leaf
  returns to active via the existing release path; no partial writes occur.
- The splitter structured-output bound for children equals `F`.
- The invariant test builds a deterministic tree through repeated splits with a
  fake splitter and asserts no node has more than `F` children.

Acceptance Criteria: implement exactly the "Acceptance criteria" list under
Delivery 8 in `delivery_plan.md`.

Validation:
```bash
python3 -m compileall src tests
uv run pytest tests/application/usecases/test_split.py -q
uv run pytest tests/integration/test_fanout_flow.py -q
task test
```

Guardrails:
- Preserve the existing `Split` release and rollback semantics.
- No new abstractions; this is a policy and a proof, not a new subsystem.
- Update `docs/architecture.md` and config docs if the split contract or the new
  setting changes a documented boundary.

Out of Scope:
- Re-clustering existing branch children.
- Depth balancing; depth is allowed to grow with content density by design.
- If the user later wants internal nodes to gain children over time, that
  reopens the documents-on-leaves invariant and is a separate design task; do not
  implement it here.

Output Format:
- Changed files; reasoning summary; validation evidence; remaining risks.
