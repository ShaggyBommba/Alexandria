from __future__ import annotations

from uuid import UUID

from application.exceptions import (
    IngestDependencyError,
    IngestLeafError,
    MissingUnitOfWork,
)
from application.ports import DocIn, Embedder, NodeHit, Summarizer, UnitOfWork
from application.usecases.route import Route
from application.usecases.seed import Seed
from domain.entity import Document, Job, Node
from domain.values import JobKind


def document_text(doc: DocIn) -> str:
    """Return stable text used for document embedding."""
    return f"{doc.name}\n\n{doc.body}"


def leaf_order(hit: NodeHit) -> tuple[float, str]:
    """Sort leaf candidates by closest distance with stable id ties."""
    return (hit.distance, str(hit.node.id))


class Ingest:
    """Attaches one document to the best matching leaf.

    Flow: summarize and embed the document, ensure the root exists, route
    through the tree, persist the document on the chosen leaf, then queue
    split-check work when the leaf becomes full.

    Implementation contract:

    - Use the configured `UnitOfWork`, `Embedder`, `Summarizer`, `Seed`, and
      `Route` dependencies. Missing required dependencies should fail with an
      application-layer error instead of silently skipping work.
    - Summarize the incoming `DocIn`, embed deterministic document text, then
      call `seed.run()` before routing so the tree has an entrypoint.
    - Use `route.run(...)` to choose candidate leaves. Attach the document to
      the nearest active leaf; if no valid leaf exists after seeding and
      routing, fail explicitly rather than writing to a branch.
    - Persist a `Document` with the original name, body, source key, generated
      summary, chosen leaf id, and embedding. Update the chosen leaf's
      `doc_count` consistently with stored documents.
    - Append an idempotent `split.check` job only when the explicit leaf
      fullness policy says the leaf is full. The node id should be the outbox
      key so duplicate publications collapse.
    - Commit the document write, count update, and outbox append in one unit of
      work.
    """

    def __init__(
        self,
        uow: UnitOfWork | None = None,
        embedder: Embedder | None = None,
        summarizer: Summarizer | None = None,
        seed: Seed | None = None,
        route: Route | None = None,
        max_leaf_docs: int | None = None,
        route_limit: int = 10,
    ) -> None:
        self.uow = uow
        self.embedder = embedder
        self.summarizer = summarizer
        self.seed = seed
        self.route = route
        self.max_leaf_docs = max_leaf_docs
        self.route_limit = route_limit

    async def run(self, doc: DocIn) -> UUID:
        """Persist one document and queue split work when needed."""
        if self.uow is None:
            raise MissingUnitOfWork("Ingest requires a UnitOfWork")
        if self.embedder is None:
            raise IngestDependencyError("Ingest requires an Embedder")
        if self.summarizer is None:
            raise IngestDependencyError("Ingest requires a Summarizer")
        if self.seed is None:
            raise IngestDependencyError("Ingest requires a Seed use case")
        if self.route is None:
            raise IngestDependencyError("Ingest requires a Route use case")

        summary = await self.summarizer.summarize(doc)
        embedding = await self.embedder.embed(document_text(doc))

        await self.seed.run()
        candidates = await self.route.run(embedding, limit=self.route_limit)
        leaf = self.pick_leaf(candidates)
        if leaf is None:
            raise IngestLeafError("Ingest could not find an active leaf")

        item = Document(
            leaf_id=leaf.id,
            source_key=doc.source_key,
            name=doc.name,
            summary=summary,
            body=doc.body,
            embedding=embedding,
        )

        uow = self.uow
        doc_id = await uow.docs.add(item)
        leaf.doc_count = await uow.nodes.count(leaf.id)
        await uow.nodes.save(leaf)

        if self.leaf_is_full(leaf.doc_count):
            await uow.outbox.append(
                Job(
                    kind=JobKind.SPLIT_CHECK,
                    payload={"node_id": str(leaf.id)},
                    key=leaf.id,
                )
            )

        await uow.commit()
        return doc_id

    def pick_leaf(self, candidates: list[NodeHit]) -> Node | None:
        """Return the nearest active leaf candidate."""
        leaves = [
            hit
            for hit in candidates
            if hit.node.kind == "leaf" and hit.node.status == "active"
        ]
        if not leaves:
            return None

        return sorted(leaves, key=leaf_order)[0].node

    def leaf_is_full(self, doc_count: int) -> bool:
        """Return whether the configured fullness policy marks a leaf full."""
        return self.max_leaf_docs is not None and doc_count >= self.max_leaf_docs
