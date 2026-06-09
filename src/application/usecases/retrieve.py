from __future__ import annotations

from application.ports import DocHit, Embedder, ReferenceRepo, Search
from application.usecases.rerank import Rerank
from application.usecases.route import Route


class Retrieve:
    """Finds documents by routing first, then searching scoped content.

    Flow: embed the query, route through the semantic tree, expand candidate
    leaves through directed references, search documents inside that scoped leaf
    set, and optionally rerank the deterministic hits.

    Implementation contract:

    - Use the configured `Embedder`, `Route`, and `Search` dependencies.
      Missing required dependencies should fail with an application-layer error.
    - Treat `limit <= 0` as an empty result. Do not call external dependencies
      when no results can be returned.
    - Call `route.run(query_embedding, limit=limit)` and build the initial leaf
      set from returned `NodeHit` values.
    - If a `ReferenceRepo` is configured, expand the leaf set with
      `refs.near(...)` using the same query embedding. Reference expansion
      widens scope only; it should not rank final documents.
    - Call `search.find(query, query_embedding, leaves, limit)` for scoped
      hybrid retrieval. Do not use `DocumentRepo` directly for ranking or
      hybrid search.
    - If a `Rerank` use case is configured, pass search hits through it.
      Otherwise return deterministic search hits capped by `limit`.
    """

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
