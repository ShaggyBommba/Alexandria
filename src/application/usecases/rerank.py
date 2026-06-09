from __future__ import annotations

from application.ports import DocHit, Ranker


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

    async def run(self, query: str, hits: list[DocHit], limit: int = 10) -> list[DocHit]:
        """Return ranked document hits using the adapter or deterministic scores."""
        raise NotImplementedError("Rerank.run is not implemented yet")
