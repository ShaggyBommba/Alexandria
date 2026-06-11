from __future__ import annotations

from collections import Counter
from logging import getLogger
from math import isfinite, log
import re
from uuid import UUID

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

    doc_terms = {
        doc.id: tokens(f"{doc.summary}\n{doc.body}")
        for doc in docs
    }
    doc_lengths = {doc_id: len(terms) for doc_id, terms in doc_terms.items()}
    avg_length = sum(doc_lengths.values()) / len(doc_lengths)
    if avg_length <= 0:
        return {doc.id: 0.0 for doc in docs}

    term_frequencies = {
        doc_id: Counter(terms)
        for doc_id, terms in doc_terms.items()
    }
    document_count = len(docs)
    query_counts = Counter(query_terms)
    document_frequencies = {
        term: sum(1 for counts in term_frequencies.values() if counts[term] > 0)
        for term in query_counts
    }

    scores: dict[UUID, float] = {}
    for doc in docs:
        score = 0.0
        doc_id = doc.id
        length = doc_lengths[doc_id]
        frequencies = term_frequencies[doc_id]
        for term, query_frequency in query_counts.items():
            frequency = frequencies[term]
            if frequency <= 0:
                continue

            document_frequency = document_frequencies[term]
            idf = log(
                1.0
                + (document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            denominator = frequency + BM25_K1 * (
                1.0 - BM25_B + BM25_B * length / avg_length
            )
            score += query_frequency * idf * (
                frequency * (BM25_K1 + 1.0) / denominator
            )

        scores[doc_id] = score

    return scores


class SqlSearch:
    """Finds scoped documents with deterministic hybrid scoring."""

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

        lexical_scores = bm25_scores(query, list(docs))
        max_lexical = max(lexical_scores.values(), default=0.0)

        hits: list[DocHit] = []
        for doc in docs:
            distance = cosine_distance(embedding, list(doc.embedding))
            lexical = lexical_scores[doc.id]
            normalized_lexical = lexical / max_lexical if max_lexical > 0 else 0.0
            similarity = vector_similarity(distance)
            score = BM25_WEIGHT * normalized_lexical + VECTOR_WEIGHT * similarity
            hits.append(
                DocHit(
                    doc=doc,
                    score=score,
                    distance=distance,
                    bm25=lexical,
                )
            )

        hits.sort(
            key=lambda hit: (
                -hit.score,
                -(hit.bm25 or 0.0),
                hit.distance if hit.distance is not None else float("inf"),
                str(hit.doc.id),
            )
        )

        logging.debug(
            "deterministic hybrid search scored documents",
            extra={
                "query_length": len(query),
                "leaf_count": len(leaves),
                "document_count": len(docs),
                "hit_count": len(hits),
                "limit": limit,
                "max_bm25": max_lexical,
            },
        )
        return hits[:limit]
