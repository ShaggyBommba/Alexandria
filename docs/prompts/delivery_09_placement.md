Role: You are the "Delivery 9 Implementation Agent" for Alexandria. Act as the
Orchestrator Agent. Use the Multi-Agent Change workflow from `docs/workflows.md`
because this adds an application port, a new infrastructure adapter, config, and
changes the ingest use case; simulate the roles sequentially if subagents are
unavailable.

Objective: Deliver "Ambiguity-Gated LLM Placement." Embed the generated document
summary, gather candidate leaves by embedding recall, and invoke an LLM `Placer`
only when the margin gate or the outlier gate fires; otherwise take the nearest
leaf. The default path with no placer configured stays deterministic
embedding-nearest with no token cost.

Required Context:
Load and follow `AGENTS.md`, `docs/rules.md`, `docs/workflows.md`,
`docs/architecture.md`, and `docs/tests.md` before planning, editing, or
validating. Read the "Epic: Hierarchical Summarization Tree" preamble and the
"Delivery 9" section of `delivery_plan.md`.

Prerequisite: Delivery 1 (Ingest). Benefits from Delivery 7's fresh summaries
but does not require it.

Greenfield: nothing is live. No backward-compatibility shims or regression
scaffolds. Worktree Safety: inspect first; unrelated dirty files are user-owned;
edit only what this delivery requires.

Scope (read each before editing):
- `src/application/usecases/ingest.py` — embed the generated summary instead of
  `name + body`; replace the nearest-leaf selection with the gated placement
  decision.
- `src/application/ports.py` — add a `Placer` protocol (document summary +
  candidate nodes -> chosen leaf id).
- `src/infrastructure/agents/placer.py` — new `LangPlacer` adapter and
  `make_placer` factory, provider `none` by default, validating the chosen id
  against the candidate set.
- `src/infrastructure/config.py` — add placement settings: `place_margin`,
  `place_outlier`, and a minimum-candidate guard (extend `IngestSettings` or add
  a `PlacerSettings` section, consistent with the existing provider sections).
- `src/infrastructure/exceptions.py` and `src/application/exceptions.py` — add
  placer/placement errors.
- `src/application/app.py` — lazy placer construction, mirroring the ranker.
- `tests/application/usecases/test_ingest.py` — both gates and the no-placer
  fallback.
- `tests/infrastructure/agents/test_placer.py` — new, with a fake client.
- `tests/integration/test_placement_flow.py` — new.
- `sandbox/09_placement_smoke.ipynb` — deterministic walkthrough using fakes.

Behavior Contract:
- Change the embedded ingest text to the generated summary so documents and node
  descriptions share an embedding space. The summary is already produced earlier
  in ingest.
- After route recall returns candidate leaves with distances, compute `d1` (the
  nearest) and `d2` (the runner-up). Escalate to placement when
  `(active leaf candidates >= 2 and d2 - d1 < place_margin)` or
  `d1 > place_outlier`, and only when a `Placer` is configured; otherwise take
  the nearest leaf.
- The `Placer` takes the document summary and the candidate nodes (id, name,
  description) and returns one chosen candidate leaf id. Validate that the
  returned id is in the candidate set; reject unknown ids with a typed error and
  fall back to the nearest leaf. On an outlier with no acceptable candidate, fall
  back to the nearest leaf; v1 does not create new structure.
- With no placer configured, ingest behaves exactly as today's deterministic
  embedding-nearest path.
- Log the gate decision at `debug` (distances, candidate ids, chosen id, gate
  reason) without changing public return shapes.

Acceptance Criteria: implement exactly the "Acceptance criteria" list under
Delivery 9 in `delivery_plan.md`.

Validation:
```bash
python3 -m compileall src tests
uv run pytest tests/application/usecases/test_ingest.py -q
uv run pytest tests/infrastructure/agents/test_placer.py -q
uv run pytest tests/integration/test_placement_flow.py -q
task test
```

Guardrails:
- Placement is a use-case decision; the `Placer` adapter only translates the
  provider call and validates ids. No provider SDK in the application layer.
- Validate untrusted placer output (the chosen id) against the candidate set
  before it drives the attachment.
- Keep public return shapes unchanged; expose diagnostics through `debug` logs,
  not new ports.
- Inject settings through constructors.
- Update `docs/architecture.md` in this same change (Ingest flow with gated
  placement, new `Placer` port, placement config).

Out of Scope:
- Creating new structure for true outliers.
- Retrieval reranking, which is owned by `Rerank`.

Output Format:
- Changed files; reasoning summary; validation evidence; remaining risks.
