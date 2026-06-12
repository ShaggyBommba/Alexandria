Role: You are the "Delivery 7 Implementation Agent" for Alexandria. Act as the
Orchestrator Agent. Because this change crosses the domain, application,
infrastructure, and presentation layers, run the Multi-Agent Change workflow
(Orchestrator, Coder, Reviewer) from `docs/workflows.md`. If subagents are
unavailable, simulate the roles sequentially in the main thread and preserve the
review loop.

Objective: Deliver "Summaries Back-Propagate On Split." After a leaf splits, the
new branch's description and embedding must be regenerated as a summary of its
children, and ancestor descriptions and embeddings must refresh upward through a
coalesced, damped worker job that stops below the root. Node embedding stays
`embed(description)` and is re-derived on every refresh.

Required Context:
Load and follow `AGENTS.md`, `docs/rules.md`, `docs/workflows.md`,
`docs/architecture.md`, and `docs/tests.md` before planning, editing, or
validating. Read the "Epic: Hierarchical Summarization Tree" preamble and the
"Delivery 7" section of `delivery_plan.md`; that section is the authoritative
scope and acceptance list.

Prerequisite: Delivery 3 (Split) is implemented. No other epic delivery is
required first.

Greenfield: nothing is live or in production. Do not add backward-compatibility
shims, migrations, or regression scaffolds. Prove correctness only with the
focused and integration tests listed under Validation.

Worktree Safety: inspect the worktree before editing. The repository has
unrelated dirty files; treat them as user-owned and do not touch, revert, or
reformat them. Edit only the files this delivery requires.

Scope (read each before editing):
- `src/domain/values.py` — add `JobKind.NODE_REFRESH = "node.refresh"`.
- `src/application/ports.py` — add a `Generalizer` protocol (node + children ->
  parent description).
- `src/infrastructure/config.py` — add `GeneralizeSettings` (provider `none`
  default, model, base_url, timeout, `refresh_epsilon`) and wire it into
  `Settings`.
- `src/infrastructure/agents/summarizer.py` and `splitter.py` — the adapter
  pattern to mirror (structured output, `make_*` factory, provider gating).
- `src/infrastructure/agents/generalizer.py` — new `LangGeneralizer` adapter and
  `make_generalizer` factory.
- `src/infrastructure/exceptions.py` — add generalizer config/response errors as
  needed, following the existing splitter error names.
- `src/application/exceptions.py` — add Generalize use-case errors.
- `src/application/usecases/generalize.py` — new `Generalize` use case.
- `src/application/usecases/split.py` — enqueue `node.refresh` for the source
  branch in the split commit.
- `src/application/app.py` — lazy generalizer construction and an `App.refresh`
  facade method.
- `src/presentation/worker/app.py` — dispatch `node.refresh -> app.refresh ->
  mark`, mirroring the existing `split.check` handler.
- `tests/application/usecases/test_generalize.py` — new.
- `tests/infrastructure/agents/test_generalizer.py` — new.
- `tests/integration/test_backprop_flow.py` — new.
- `sandbox/07_backprop_smoke.ipynb` — deterministic walkthrough using fakes.

Implementation Order (follow the preferred order in `docs/workflows.md`):
values/config -> ports -> infrastructure adapter -> application use case ->
split producer -> app wiring -> worker -> docs and notebook.

Behavior Contract — `Generalize.run(node_id)`:
- Load the node and its children through `uow.nodes.kids(node_id)`. A node with
  no children is a no-op; return without writes.
- Produce the parent description from the children through the `Generalizer`
  port. Reject empty or blank output with a typed application error.
- Embed the new description through the configured `Embedder` so the node
  embedding stays `embed(description)` and dimension-correct.
- Compute cosine movement between the new embedding and the stored embedding.
  When movement is at most `refresh_epsilon`, do not write and do not enqueue a
  parent refresh (damping; stop the propagation).
- When movement exceeds `refresh_epsilon`, save the node with the new
  description and embedding and a bumped `version`; if the node has a parent and
  that parent is not the root, append one idempotent `node.refresh` job keyed by
  the parent id. Commit the description write and the parent enqueue together in
  one unit of work.
- Never refresh the root node's own description.
- Do not hold a database transaction open during the `Generalizer` call (mirror
  `Split`): generalize outside the write transaction, then commit the write plus
  enqueue.

Behavior Contract — `Split` change:
- After the split commits its children and marks the source a branch, append a
  `node.refresh` job keyed by the source (now-branch) id, inside the split's
  unit of work, so the branch summary is regenerated from its fresh children.

Behavior Contract — App and Worker:
- Construct the generalizer lazily: build it only when an injected fake is absent
  and the provider is enabled, mirroring the splitter and ranker wiring.
- Add `App.refresh(node_id)` that runs `Generalize`.
- The worker claims `node.refresh`, validates the `node_id` payload, calls
  `app.refresh`, and marks the job done; malformed payloads fail terminally with
  `mark(..., retry=False)`, mirroring the `split.check` handler.

Acceptance Criteria: implement exactly the "Acceptance criteria" list under
Delivery 7 in `delivery_plan.md`. Do not mark the delivery complete until each
is demonstrably true.

Validation:
```bash
python3 -m compileall src tests
uv run pytest tests/application/usecases/test_generalize.py -q
uv run pytest tests/infrastructure/agents/test_generalizer.py -q
uv run pytest tests/application/usecases/test_split.py tests/application/test_app.py -q
uv run pytest tests/integration/test_backprop_flow.py -q
task test
```

Guardrails:
- Application use cases decide; repositories persist; adapters translate.
  LangChain and provider SDKs stay in infrastructure.
- Validate untrusted generalizer output before it drives any write.
- Use the outbox for durable-write-plus-async-publication; key `node.refresh` by
  node id so duplicate publications coalesce.
- Log decisions at `debug` (node id, movement, enqueue or stop) without changing
  public return shapes or expanding ports for diagnostics.
- Keep `App` a thin facade; inject settings through constructors.
- Update `docs/architecture.md` in this same change (new `node.refresh` job kind,
  `Generalizer` port, `Generalize` use case, `App.refresh`, worker dispatch),
  per the documentation update triggers in `docs/workflows.md`.

Output Format:
- Changed files.
- Reasoning summary.
- Validation evidence (commands run with pass or fail).
- Remaining risks or intentionally deferred follow-up.
