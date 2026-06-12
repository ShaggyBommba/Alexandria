from __future__ import annotations

import logging
from uuid import UUID

from application.exceptions import (
    IngestDependencyError,
    IngestLeafError,
    MissingUnitOfWork,
)
from application.ports import (
    DocIn,
    Embedder,
    FullnessPolicy,
    NodeHit,
    Summarizer,
    UnitOfWork,
)
from application.usecases.route import Route
from application.usecases.seed import Seed
from domain.entity import Document, Job, Node
from domain.values import JobKind

logger = logging.getLogger(__name__)


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
    - Append an idempotent `split.check` job only when the injected leaf
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
        fullness: FullnessPolicy | None = None,
        route_limit: int = 10,
    ) -> None:
        self.uow = uow
        self.embedder = embedder
        self.summarizer = summarizer
        self.seed = seed
        self.route = route
        self.fullness = fullness
        self.route_limit = route_limit

    async def run(self, doc: DocIn) -> UUID:
        """Persist one document and queue split work when needed."""
        logger.info("ingest started source_key=%s name=%s", doc.source_key, doc.name)
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
        if self.fullness is None:
            raise IngestDependencyError("Ingest requires a FullnessPolicy")

        logger.info("ingest summarizing source_key=%s", doc.source_key)
        summary = await self.summarizer.summarize(doc)
        logger.info("ingest embedding source_key=%s", doc.source_key)
        embedding = await self.embedder.embed(document_text(doc))

        logger.info("ingest seeding and routing source_key=%s", doc.source_key)
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

        # Update the count on a node owned by the unit-of-work session. The routed
        # leaf belongs to the read session used by Route, and writing it there
        # would deadlock the write session against the read session on Postgres.
        node = await uow.nodes.get(leaf.id)
        if node is None:
            raise IngestLeafError("Ingest lost the routed leaf before persisting")
        node.doc_count = await uow.nodes.count(node.id)
        await uow.nodes.save(node)

        if self.fullness.full(node.doc_count):
            logger.info(
                "ingest queueing split check source_key=%s leaf_id=%s doc_count=%s",
                doc.source_key,
                node.id,
                node.doc_count,
            )
            await uow.outbox.append(
                Job(
                    kind=JobKind.SPLIT_CHECK,
                    payload={"node_id": str(node.id)},
                    key=node.id,
                )
            )

        await uow.commit()
        logger.info(
            "ingest committed source_key=%s doc_id=%s leaf_id=%s doc_count=%s",
            doc.source_key,
            doc_id,
            node.id,
            node.doc_count,
        )
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
