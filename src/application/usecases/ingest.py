from __future__ import annotations

from uuid import UUID

from application.ports import DocIn, Embedder, Summarizer, UnitOfWork
from application.usecases.route import Route
from application.usecases.seed import Seed


class Ingest:
    """Attaches one document to the best matching leaf."""

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
