from __future__ import annotations

import logging

from application.ports import DocHit, Ranker

logger = logging.getLogger(__name__)


class Rerank:
    """Reorders document candidates for a query.

    Flow: accept hybrid-search candidates, call the ranking adapter when one is
    configured, and return the final top hits for the caller.

    Implementation contract:

    - If no `Ranker` is configured, keep retrieval deterministic by returning
      the highest-scored `DocHit` values, capped by `limit`.
    - If a `Ranker` is configured, delegate to `ranker.rank(query, hits, limit)`
      and return its result without adding persistence or provider-specific
      behavior here.
    - Treat `limit <= 0` as an empty result, and do not mutate the incoming
      `hits` list.
    """

    def __init__(self, ranker: Ranker | None = None) -> None:
        self.ranker = ranker

    async def run(
        self, query: str, hits: list[DocHit], limit: int = 10
    ) -> list[DocHit]:
        """Return ranked document hits using the adapter or deterministic scores."""
        logger.info("rerank started query_len=%s hits=%s limit=%s", len(query), len(hits), limit)
        if limit <= 0:
            logger.info("rerank skipped because limit is not positive")
            return []

        if self.ranker is not None:
            logger.info("rerank calling ranker hits=%s", len(hits))
            ranked = await self.ranker.rank(query, hits, limit)
            logger.info("rerank finished ranked_hits=%s", len(ranked))
            return ranked

        ranked = sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]
        logger.info("rerank finished deterministic_hits=%s", len(ranked))
        return ranked
