from __future__ import annotations

from uuid import UUID

from application.ports import DocIn, Embedder, Summarizer, UnitOfWork
from application.usecases.route import Route
from application.usecases.seed import Seed


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
    ) -> None:
        self.uow = uow
        self.embedder = embedder
        self.summarizer = summarizer
        self.seed = seed
        self.route = route

    async def run(self, doc: DocIn) -> UUID:
        """Persist one document and queue split work when needed."""
        raise NotImplementedError("Ingest.run is not implemented yet")
