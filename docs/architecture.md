# Architecture

This document is the repository-specific architecture source of truth for
Alexandria. General coding standards belong in `docs/rules.md`; this file
describes the current Alexandria model, boundaries, workflows, and
implementation order.

Alexandria is a dynamic semantic index. Documents are attached to leaf nodes in
a tree. Nodes and documents have embeddings. Document bodies and summaries are
also available to BM25-style lexical search. Leaf nodes have directed semantic
references to other leaves. As the database grows, full leaves are queued for
LLM-assisted splitting so the index can expand.

## Layers

Runtime layers:

- `domain` contains the current shared-kernel durable entities and value enums.
- `application` contains ports, typed boundary shapes, and implemented usecase
  workflows.
- `infrastructure` contains SQL setup, concrete repositories, queue/outbox
  adapters, config, observability, and provider adapters.
- `presentation` is the entrypoint layer for API, CLI, MCP, and worker
  processes.

The intended dependency direction is:

```text
presentation -> application -> domain
infrastructure -> application ports
```

The current domain models are shared-kernel SQLAlchemy models by explicit
choice. This is a local architecture decision for Alexandria. New persistence
behavior should still keep decisions out of repositories and use application
ports for swappable dependencies.

## Domain Model

Current durable entities live in `src/domain/entity.py`.

### Node

`Node` maps to `nodes` and represents one semantic tree node.

Important fields:

- `id`
- `parent_id`
- `name`
- `description`
- `embedding`
- `kind`: `branch` or `leaf`
- `status`: `active`, `splitting`, or `retired`
- `doc_count`
- `version`

Relationships:

- `parent`
- `children`
- `documents`
- `references`
- `referenced_by`

Runtime meaning:

- Branch nodes route traversal to children.
- Leaf nodes own documents.
- A full active leaf can be queued for split evaluation.
- A successfully split leaf becomes an active branch with child leaves.

### Document

`Document` maps to `documents` and represents stored content attached to one
leaf.

Important fields:

- `id`
- `leaf_id`
- `source_key`
- `name`
- `summary`
- `body`
- `embedding`

Runtime meaning:

- A document belongs to one current leaf.
- `source_key` is the optional idempotency key for external source identity.
- `embedding` supports vector search inside routed leaf scope.
- `body` and `summary` support BM25-style lexical search inside routed leaf
  scope.
- Retrieval returns document hits after tree routing, reference expansion,
  hybrid search, and ranking.

### Reference

`Reference` maps to the quoted SQL table name `references`.

Important fields:

- `id`
- `from_node_id`
- `to_node_id`
- `distance`
- `rank`
- `method`

Runtime meaning:

- References are directed semantic links between nodes, normally active leaves.
- Retrieval can expand from routed leaves to referenced leaves.
- Split and reference rebuild flows should remove stale references and replace
  outgoing references for affected leaves.

### Job

`Job` maps to `outbox` and represents durable queued work.

Important fields:

- `id`
- `key`
- `kind`
- `payload`
- `status`: `pending`, `running`, `done`, or `failed`
- `attempts`
- `max_attempts`
- `available_at`
- `locked_at`
- `done_at`
- `last_error`

Current job kind used by the index:

- `split.check`

## Application Ports

Shared ports and boundary values live in `src/application/ports.py`.

Current result shapes:

- `NodeHit`
- `DocHit`: document plus hybrid score, optional vector distance, and optional
  BM25 score
- `RefHit`

Current input and adapter-output shapes:

- `DocIn`
- `ChildPlan`
- `SplitPlan`

Current external-service ports:

- `Embedder`
- `Summarizer`
- `Splitter`
- `Search`
- `Ranker`

Current policy ports:

- `FullnessPolicy`

Current concrete adapters for these ports:

- `OpenAIEmbedder` in `src/infrastructure/embeddings.py` implements
  `Embedder` through the OpenAI SDK. It is selected by passing
  `EmbeddingProvider.OPENAI` to `make_embedder`, configured through
  `Settings.embedding`, and wired into `App` through lazy construction for
  `Ingest` and `Retrieve`. Missing OpenAI-compatible embedding API keys raise
  `EmbedderConfigError` when the embedding path is first used.
- `LangSummarizer` in `src/infrastructure/agents/summarizer.py` implements
  `Summarizer` through a LangChain chat model and structured response
  validation. It is wired into `App` through a deferred construction path, so
  summarizer configuration is validated when the adapter is first used.
- `LangSplitter` in `src/infrastructure/agents/splitter.py` implements
  `Splitter` through a LangChain chat model and structured `SplitPlan`
  validation. The chat model returns each child's name, description, and
  assigned document ids; child embeddings are derived by embedding the child
  description through the configured `Embedder`, not returned by the model, so
  they stay compatible with the configured vector dimension. It is disabled by
  default through `Settings.splitter.provider = "none"` and can be enabled with
  explicit provider config. Missing provider-backed splitter API keys raise
  `SplitterConfigError`. Tests and notebooks may still inject local fake
  splitters directly into `App`.
- `LangRanker` in `src/infrastructure/agents/ranker.py` implements `Ranker`
  through a LangChain chat model and structured ranked document ids. It is
  disabled by default through `Settings.ranker.provider = "none"`, rejects
  missing provider-backed API keys with `RankerConfigError`, rejects unknown or
  duplicate document ids, and can be injected or configured without changing
  retrieval workflow decisions.
- `SqlSearch` in `src/infrastructure/search.py` implements `Search` through a
  scoped SQL document lookup and a pluggable in-process `SearchPolicy`.
  `HybridSearch` is the default policy and combines normalized BM25 with
  clamped vector similarity. `VectorSearch` scores only by embedding distance,
  and `LexicalSearch` scores only by BM25 over document body and summary.
  Policies return stable `DocHit` ordering and populate score components they
  know.

Current repository and transaction ports:

- `NodeRepo`
- `DocumentRepo`
- `ReferenceRepo`
- `OutboxRepo`
- `UnitOfWork`

Repositories should persist and fetch. They should not decide traversal policy,
fullness policy, split policy, retry behavior, hybrid search behavior, or
ranking behavior.

`DocumentRepo` is persistence-focused. It should store, load, move, save, and
remove documents. It should not own BM25/vector hybrid retrieval.

The `Search` port owns document retrieval inside an already-scoped leaf set. A
concrete infrastructure adapter may combine embeddings, BM25, SQL, database
extensions, or external search engines behind this port.

## App Wiring And Startup

`App` is the workflow facade. It wires settings, `Db`, SQL repositories,
`SqlUnitOfWork`, `SqlSearch`, provider adapters, and use cases. `App.setup()`
calls `Db.create_all()` before workflow use so local development can start from
an empty database.

Provider construction is lazy where metadata paths should stay cheap:

- embeddings are built on first `embed(...)`
- splitter and ranker construction only happens when an injected fake is not
  supplied and their provider setting is enabled

The summarizer is built eagerly through `make_summarizer` during `App`
construction, so a configured provider-backed summarizer requires its API key
when an `App` is created.

Metadata entrypoints stay lightweight. API `GET /health` and `GET /version`
return configured process metadata without constructing a workflow `App` when
one was not injected. CLI `version` reads settings directly. Ingest, retrieve,
refs, MCP tools, and worker paths still construct `App` and therefore require
configured database access.

## Database Setup Strategy

Local and test app wiring use SQLAlchemy metadata creation, not migrations.
`Db.create_all()` first ensures the pgvector extension exists for PostgreSQL
through `CREATE EXTENSION IF NOT EXISTS vector`, then calls
`Base.metadata.create_all(...)`.

This is the explicit development strategy for the current repository state.
Alembic or another migration system is deferred until production deployment or
schema-evolution requirements are added.

## Outbox

The current outbox API is intentionally small:

```text
append
due
claim
mark
```

`append` inserts or revives an idempotent job. `due` reads ready pending jobs
without locking. `claim` locks ready jobs and marks them running. `mark`
transitions claimed jobs to `pending`, `done`, or `failed` behavior based on
`JobStatus`. Worker boundaries may call `mark(..., retry=False)` for malformed
payloads that should fail terminally instead of requeueing.

Do not reintroduce older convenience names such as `add`, `jobs`, `release`,
`done`, or `fail` for current outbox behavior. Use `append`, `due`, `claim`,
and `mark`.

The durable split-check producer should use the node id as the job idempotency
key when duplicate split publication is possible.

## Usecases

Current usecases live in `src/application/usecases`.

### Seed

Creates or returns the root node. Ingest and retrieval need a stable tree
entrypoint before routing can start.

### Route

Walks the tree by embedding distance and returns candidate leaves. This is the
shared traversal boundary for ingest and retrieval. Beam-search policy belongs
here, not in repositories.

### Ingest

Accepts `DocIn`, embeds and summarizes the document through ports, routes to a
leaf, persists the document, updates node counts, and appends a `split.check`
job when the configured `Settings.ingest.max_leaf_docs` threshold marks the
leaf full.

The document write, count update, and outbox append should share one unit of
work when the split job must be durable.

### Lint

Worker-facing usecase for `split.check`. It reloads the node after the job is
claimed, checks whether it still needs splitting, and delegates to `Split` when
the current state still requires work.

### Split

Splits a full leaf into child nodes and redistributes documents. It calls the
`Splitter` port, validates the returned `SplitPlan` against local document ids,
creates children, moves documents, updates the parent node, and clears stale
references. Reference rebuild remains a separate `Refs` workflow.

Do not hold a database transaction open during the LLM call. Mark the source
leaf as `splitting` before the call so new routing will not target it, validate
local truth after the call, then commit the child, document, source, and stale
reference changes together. If the splitter fails or returns an invalid plan,
restore the source leaf to `active`.

### Refs

Rebuilds directed semantic references for one node. It should clear stale
outgoing references, compare against active leaves, and write the top ranked
references.

### Retrieve

Embeds a query, routes through the tree, expands the candidate set through
references, runs hybrid document search inside the scoped leaves, and returns
ranked document hits.

Retrieval should not call `DocumentRepo` for ranking or hybrid lookup.
`DocumentRepo` persists documents; `Search` finds relevant documents.

### Rerank

Reorders document candidates through the `Ranker` port when deterministic
distance ranking is not enough. Keep deterministic retrieval working before
adding LLM reranking.

## Worker

The worker in `src/presentation/worker/app.py` claims outbox jobs by kind,
calls the application boundary, and marks jobs through the current outbox API:

```text
claim -> app.lint -> mark
```

Workers should call application usecases or app facade methods. They should not
perform repository-level split or reference decisions directly.

## Presentation Entrypoints

Public workflow entrypoints live under `src/presentation`.

Current public local surfaces:

- FastAPI exposes `GET /health`, `GET /version`, `POST /ingest`, and
  `GET /retrieve`.
- Click exposes `version`, `ingest`, `retrieve`, and `refs` commands.
- MCP exposes `ingest` and `retrieve` tools through `FastMCP` and runs the
  streamable HTTP transport from the `mcp` console entrypoint.

Entrypoints validate transport input, translate it into application boundary
values such as `DocIn`, call `App`, and serialize transport responses. API
workflow requests use request-scoped `App` instances so routing and search do
not share a long-lived SQLAlchemy session across requests. They translate
expected `BaseError` failures into transport-specific errors: API 400 payloads,
`click.ClickException`, or MCP tool errors.

Entrypoints should not import repositories for workflow decisions. Document hit
responses expose client-useful document fields and scores, but not embeddings
or ORM internals.

## Retrieval Flow

Expected retrieval shape:

```text
query
embed query
route through tree to candidate leaves
expand candidate leaves through references
hybrid search scoped documents with embedding and BM25
rerank
return top results
```

Keep tree routing and hybrid document search as separate boundaries. Retrieval
remains deterministic when no ranker is configured; provider-backed ranking is
an optional adapter behind `Rerank`, not a change to routing or search policy.

## Ingest Flow

Expected ingest shape:

```text
document input
summarize and embed document
ensure root exists
route to candidate leaves
choose attachment leaf
write document and update node count
append split.check job when full
commit
```

When the document write and queued split work must be atomic, write both inside
one `UnitOfWork`.

## Split Flow

Expected split shape:

```text
worker claims split.check
lint reloads node
skip if no longer full or no longer active
load documents for node
call splitter outside the write transaction
validate child plan against local documents
create children
move documents
update parent node state
clear stale references
append follow-up work if needed
commit
mark job
```

The splitter output is untrusted adapter output. It must be checked against
known node ids and document ids before it can drive writes.

## Implementation Order

Current preferred order:

1. Keep outbox API and tests stable around `append`, `due`, `claim`, and
   `mark`.
2. Implement SQL repositories for nodes, documents, and references.
3. Implement `SqlUnitOfWork`.
4. Implement `Seed`.
5. Implement `Route`.
6. Implement `Ingest`.
7. Implement `Lint` and `Split`.
8. Implement `Refs`.
9. Implement deterministic `Search` over scoped leaves.
10. Implement deterministic `Retrieve`.
11. Implement `Rerank`.
12. Wire concrete adapters through `App`, workers, API, CLI, and MCP.
13. Update docs when a boundary, workflow, or durable model changes.

## Validation

After code changes, run:

```bash
python3 -m compileall src
```

For test changes, also run:

```bash
python3 -m compileall tests
uv run pytest --collect-only -q
```

For outbox changes, run:

```bash
uv run pytest tests/infrastructure/repositories/test_outbox_repo.py -q
```

For app wiring changes, run:

```bash
uv run python - <<'PY'
from application.app import get_app
app = get_app()
print(app.name, app.version)
PY
```

This app wiring check requires the configured database to be reachable because
`App.setup()` creates local schema. Metadata-only API/CLI checks should use the
entrypoint tests instead of `get_app()`.

## Architecture Rules

Preserve these local boundaries unless this document is intentionally updated:

- Application usecases own workflow decisions.
- Repositories persist and fetch.
- Hybrid document retrieval goes through the `Search` port.
- External SDKs, LLM clients, and provider frameworks stay in infrastructure
  adapters.
- Multi-write workflows use a unit of work when atomicity matters.
- Durable write plus async publication uses the outbox when both must commit
  together.
- Workers and entrypoints call application boundaries.
- Settings are constructor-injected.
- `App` remains a thin facade.
