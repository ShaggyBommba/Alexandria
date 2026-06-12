from __future__ import annotations

import logging

from application.exceptions import RetrieveDependencyError
from application.ports import DocHit, Embedder, ReferenceRepo, Search
from application.usecases.rerank import Rerank
from application.usecases.route import Route

logger = logging.getLogger(__name__)


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
        logger.info("retrieve started query_len=%s limit=%s", len(query), limit)
        if limit <= 0:
            logger.info("retrieve skipped because limit is not positive")
            return []

        if self.embedder is None or self.route is None or self.search is None:
            dependencies = ", ".join(
                name
                for name, dependency in (
                    ("Embedder", self.embedder),
                    ("Route", self.route),
                    ("Search", self.search),
                )
                if dependency is None
            )
            raise RetrieveDependencyError(
                f"Retrieve requires configured dependencies: {dependencies}",
            )

        logger.info("retrieve embedding query")
        query_embedding = await self.embedder.embed(query)
        logger.info("retrieve routing query")
        routed = await self.route.run(query_embedding, limit=limit)
        leaves = {hit.node.id for hit in routed}
        logger.info("retrieve routed leaves=%s", len(leaves))
        if not leaves:
            logger.info("retrieve finished with no routed leaves")
            return []

        if self.refs is not None:
            logger.info("retrieve expanding references from leaves=%s", len(leaves))
            refs = await self.refs.near(set(leaves), query_embedding, limit)
            leaves.update(hit.node.id for hit in refs)
            logger.info("retrieve expanded scope leaves=%s refs=%s", len(leaves), len(refs))

        logger.info("retrieve searching scoped documents leaves=%s", len(leaves))
        hits = await self.search.find(query, query_embedding, leaves, limit)
        logger.info("retrieve search hits=%s", len(hits))
        if not hits:
            logger.info("retrieve finished with no search hits")
            return []

        if self.rerank is not None:
            logger.info("retrieve reranking hits=%s", len(hits))
            ranked = await self.rerank.run(query, hits, limit)
            logger.info("retrieve finished ranked_hits=%s", len(ranked))
            return ranked

        logger.info("retrieve finished hits=%s", min(len(hits), limit))
        return hits[:limit]
