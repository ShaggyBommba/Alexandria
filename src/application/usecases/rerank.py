from __future__ import annotations

from application.ports import DocHit, Ranker


class Rerank:
    """Reorders document candidates for a query."""

    def __init__(self, ranker: Ranker | None = None) -> None:
        self.ranker = ranker

    async def run(self, query: str, hits: list[DocHit], limit: int = 10) -> list[DocHit]:
        """Return the top ranked document hits."""
        raise NotImplementedError("Rerank.run is not implemented yet")
