from __future__ import annotations

from application.ports import DocHit, Embedder, ReferenceRepo, Search
from application.usecases.rerank import Rerank
from application.usecases.route import Route


class Retrieve:
    """Finds documents by routing first, then searching scoped content."""

    def __init__(
        self,
        search: Search | None = None,
        refs: ReferenceRepo | None = None,
        embedder: Embedder | None = None,
        route: Route | None = None,
        rerank: Rerank | None = None,
    ) -> None:
        self.search = search
        self.refs = refs
        self.embedder = embedder
        self.route = route
        self.rerank = rerank

    async def run(self, query: str, limit: int = 10) -> list[DocHit]:
        """Embed, route, expand references, hybrid search, then rerank."""
        raise NotImplementedError("Retrieve.run is not implemented yet")
