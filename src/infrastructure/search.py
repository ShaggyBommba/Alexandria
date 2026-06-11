from __future__ import annotations

from logging import getLogger
from math import isfinite
import re
from src.application.ports import SearchPolicy
from uuid import UUID

from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from application.ports import DocHit
from domain.entity import Document
from infrastructure.utils.vector import cosine_distance

logging = getLogger(__name__)

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
BM25_K1 = 1.5
BM25_B = 0.75
BM25_WEIGHT = 0.60
VECTOR_WEIGHT = 0.40


def tokens(text: str) -> list[str]:
    """Return lowercase alphanumeric tokens used for deterministic lexical search."""
    return TOKEN_PATTERN.findall(text.lower())


def vector_similarity(distance: float) -> float:
    """Return a clamped similarity contribution for a cosine distance."""
    if not isfinite(distance):
        return 0.0
    return max(0.0, min(1.0, 1.0 - distance))


def bm25_scores(query: str, docs: list[Document]) -> dict[UUID, float]:
    """Return raw BM25-style lexical scores keyed by document id."""
    query_terms = tokens(query)
    if not query_terms or not docs:
        return {doc.id: 0.0 for doc in docs}

    corpus = [tokens(f"{doc.summary}\n{doc.body}") for doc in docs]
    if not any(corpus):
        return {doc.id: 0.0 for doc in docs}

    ranker = BM25Okapi(corpus, k1=BM25_K1, b=BM25_B)
    scores = ranker.get_scores(query_terms)
    return {
        doc.id: float(score)
        for doc, score in zip(docs, scores, strict=True)
    }


def normalize(lexical: float, max_lexical: float) -> float:
    """Return a normalized lexical contribution for final scoring."""
    return lexical / max_lexical if max_lexical > 0 else 0.0


def ordered(hits: list[DocHit]) -> list[DocHit]:
    """Return deterministic hit ordering for all search policies."""
    return sorted(
        hits,
        key=lambda hit: (
            -hit.score,
            -(hit.bm25 or 0.0),
            hit.distance if hit.distance is not None else float("inf"),
            str(hit.doc.id),
        ),
    )





class VectorSearch:
    """Scores documents by vector similarity only."""

    def score(
        self,
        query: str,
        embedding: list[float],
        docs: list[Document],
    ) -> list[DocHit]:
        hits: list[DocHit] = []
        for doc in docs:
            distance = cosine_distance(embedding, list(doc.embedding))
            hits.append(
                DocHit(
                    doc=doc,
                    score=vector_similarity(distance),
                    distance=distance,
                    bm25=None,
                )
            )
        return ordered(hits)


class LexicalSearch:
    """Scores documents by BM25-style lexical relevance only."""

    def score(
        self,
        query: str,
        embedding: list[float],
        docs: list[Document],
    ) -> list[DocHit]:
        lexical_scores = bm25_scores(query, docs)
        max_lexical = max(lexical_scores.values(), default=0.0)

        hits = [
            DocHit(
                doc=doc,
                score=normalize(lexical_scores[doc.id], max_lexical),
                distance=None,
                bm25=lexical_scores[doc.id],
            )
            for doc in docs
        ]
        return ordered(hits)


class HybridSearch:
    """Scores documents by combining normalized BM25 and vector similarity."""

    def score(
        self,
        query: str,
        embedding: list[float],
        docs: list[Document],
    ) -> list[DocHit]:
        lexical_scores = bm25_scores(query, docs)
        max_lexical = max(lexical_scores.values(), default=0.0)

        hits: list[DocHit] = []
        for doc in docs:
            distance = cosine_distance(embedding, list(doc.embedding))
            lexical = lexical_scores[doc.id]
            lexical_score = normalize(lexical, max_lexical)
            similarity = vector_similarity(distance)
            score = BM25_WEIGHT * lexical_score + VECTOR_WEIGHT * similarity
            hits.append(
                DocHit(
                    doc=doc,
                    score=score,
                    distance=distance,
                    bm25=lexical,
                )
            )
        return ordered(hits)


class SqlSearch:
    """Finds scoped documents with a deterministic search policy."""

    def __init__(self, session: Session, policy: SearchPolicy | None = None) -> None:
        self._session = session
        self.policy = policy or HybridSearch()

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

        scoped_docs = list(docs)
        hits = self.policy.score(query, embedding, scoped_docs)

        logging.debug(
            "deterministic search scored documents",
            extra={
                "query_length": len(query),
                "leaf_count": len(leaves),
                "document_count": len(scoped_docs),
                "hit_count": len(hits),
                "limit": limit,
                "policy": type(self.policy).__name__,
            },
        )
        return hits[:limit]
