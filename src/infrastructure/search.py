from __future__ import annotations

from logging import getLogger
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from application.ports import DocHit
from domain.entity import Document
from infrastructure.utils.vector import cosine_distance

logging = getLogger(__name__)


class SqlSearch:
    """Finds scoped documents with deterministic vector scoring."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def find(
        self,
        query: str,
        embedding: list[float],
        leaves: set[UUID],
        limit: int,
    ) -> list[DocHit]:
        if not leaves or limit <= 0:
            return []

        docs = self._session.scalars(
            select(Document)
            .where(Document.leaf_id.in_(leaves))
            .order_by(Document.id.asc())
        ).all()

        hits: list[DocHit] = []
        for doc in docs:
            distance = cosine_distance(embedding, list(doc.embedding))
            hits.append(
                DocHit(
                    doc=doc,
                    score=1.0 - distance,
                    distance=distance,
                    bm25=None,
                )
            )

        hits.sort(key=lambda hit: (-hit.score, str(hit.doc.id)))

        logging.debug(
            "deterministic search scored documents",
            extra={
                "query_length": len(query),
                "leaf_count": len(leaves),
                "document_count": len(docs),
                "hit_count": len(hits),
                "limit": limit,
            },
        )
        return hits[:limit]
