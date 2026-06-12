Role: You are the "Delivery 10 Implementation Agent" for Alexandria. Act as the
Orchestrator Agent and use the Standard Change workflow from `docs/workflows.md`
(extends the generalize use case, adds a scoped sampler, a drift trigger, and a
worker path). Escalate to Multi-Agent only if scope grows.

Objective: Deliver "Summary Drift Control." Rebuild a node description from a
deterministic sample of real leaf documents in its subtree, not only from child
summaries, re-embed, and follow the same damping and propagation rules. Add a
drift trigger that enqueues rebuilds after enough subtree growth, correcting
summary-of-summary drift.

Required Context:
Load and follow `AGENTS.md`, `docs/rules.md`, `docs/workflows.md`,
`docs/architecture.md`, and `docs/tests.md` before planning, editing, or
validating. Read the "Epic: Hierarchical Summarization Tree" preamble and the
"Delivery 10" section of `delivery_plan.md`.

Prerequisite: Delivery 7.

Greenfield: nothing is live. No backward-compatibility shims or regression
scaffolds. Worktree Safety: inspect first; unrelated dirty files are user-owned;
edit only what this delivery requires.

Confirm Before Building (ask the user; if unanswered, state the assumption and
proceed): where the drift counter lives (a new durable field on `Node` versus a
derived count), and whether to reuse `node.refresh` with a rebuild mode versus
add a `node.rebuild` job kind.

Scope (read each before editing):
- `src/infrastructure/repositories/nodes.py` and/or
  `src/infrastructure/repositories/documents.py` plus
  `src/application/ports.py` — add a deterministic scoped sampler that returns
  representative leaf documents under a node. Keep repositories
  persistence-focused: this is a scoped query, not a decision.
- `src/application/usecases/generalize.py` — add a rebuild path that summarizes
  from sampled documents, or add a focused `Rebuild` use case. Re-embed and
  apply the same `refresh_epsilon` damping and parent propagation as
  `Generalize`.
- `src/infrastructure/config.py` — add a `drift_docs` threshold.
- `src/domain/values.py` — optionally add `node.rebuild`, or reuse
  `node.refresh` with a mode flag per the decision above.
- The drift trigger — a per-subtree counter of documents added since the last
  rebuild that enqueues an idempotent rebuild keyed by the node id when it
  crosses `drift_docs`. Keep the counter update inside the ingest unit of work if
  it must be durable and atomic.
- `src/presentation/worker/app.py` — dispatch the rebuild, consistent with the
  existing handlers (validate payload, mark done or failed).
- `tests/application/usecases/test_generalize.py` — rebuild path.
- `tests/integration/test_drift_flow.py` — new.
- `sandbox/10_drift_smoke.ipynb` — deterministic walkthrough using fakes.

Behavior Contract:
- The rebuild grounds the node description in sampled subtree documents, with a
  deterministic sample in tests. It re-embeds and follows the same damping and
  upward propagation rules as `Generalize`.
- The drift trigger increments per subtree on ingest and enqueues an idempotent
  rebuild when the count crosses `drift_docs`.
- Worker handling for the rebuild matches the existing job handlers: validate the
  payload, mark success done, mark malformed payloads failed terminally.

Acceptance Criteria: implement exactly the "Acceptance criteria" list under
Delivery 10 in `delivery_plan.md`.

Validation:
```bash
python3 -m compileall src tests
uv run pytest tests/application/usecases/test_generalize.py -q
uv run pytest tests/integration/test_drift_flow.py -q
task test
```

Guardrails:
- Repositories persist; the sampler is a scoped query, not a workflow decision.
  Use cases decide.
- Keep the `Generalizer` and `Summarizer` behind ports; no provider SDK in the
  application layer.
- Update `docs/architecture.md` in this same change: document the drift trigger
  location, the chosen job-kind approach, and the sampler.

Out of Scope:
- Full subtree re-summarization on every ingest.
- Tuning sample size beyond a deterministic default.

Output Format:
- Changed files; reasoning summary; validation evidence; remaining risks.
