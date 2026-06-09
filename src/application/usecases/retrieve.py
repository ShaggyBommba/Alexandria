from __future__ import annotations

from application.ports import DocHit, DocumentRepo, Embedder, ReferenceRepo
from application.usecases.rerank import Rerank
from application.usecases.route import Route


class Retrieve:
    """Finds documents relevant to a query."""

    def __init__(
        self,
        docs: DocumentRepo | None = None,
        refs: ReferenceRepo | None = None,
        embedder: Embedder | None = None,
        route: Route | None = None,
        rerank: Rerank | None = None,
    ) -> None:
        self.docs = docs
        self.refs = refs
        self.embedder = embedder
        self.route = route
        self.rerank = rerank

    async def run(self, query: str, limit: int = 10) -> list[DocHit]:
        """Return ranked documents for one query."""
        raise NotImplementedError("Retrieve.run is not implemented yet")
