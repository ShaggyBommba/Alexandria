from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from application.app import App
import application.app as app_module
from domain.entity import Base, Document, Node, VECTOR_DIMENSIONS
from infrastructure.config import IngestSettings, Settings


class MemoryDb:
    def __init__(self) -> None:
        self._engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self._sessions = sessionmaker(bind=self._engine)

    def sessions(self) -> sessionmaker[Session]:
        return self._sessions

    def session(self) -> Session:
        return self._sessions()

    def create_all(self) -> None:
        Base.metadata.create_all(self._engine)


class FakeEmbedder:
    def __init__(self, embed: Callable[[str], list[float]]) -> None:
        self.embed_text = embed
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return self.embed_text(text)


class FakeSummarizer:
    async def summarize(self, _doc) -> str:
        return "unused"


def uid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012x}")


def vector(*values: float) -> list[float]:
    embedding = [0.0] * VECTOR_DIMENSIONS
    for index, value in enumerate(values):
        embedding[index] = value
    return embedding


def deterministic_embedding(text: str) -> list[float]:
    lowered = text.lower()
    if "hydrogen" in lowered or "pressure" in lowered:
        return vector(1.0, 0.0, 0.0)
    if "payment" in lowered or "retry" in lowered:
        return vector(0.0, 1.0, 0.0)
    if "semantic" in lowered or "vector" in lowered:
        return vector(0.0, 0.0, 1.0)
    return vector(0.0, 0.0, 1.0)


def make_app(monkeypatch) -> tuple[App, MemoryDb, FakeEmbedder]:
    db = MemoryDb()
    embedder = FakeEmbedder(deterministic_embedding)

    monkeypatch.setattr(app_module, "Db", lambda _settings: db)
    monkeypatch.setattr(
        app_module,
        "make_embedder",
        lambda _provider, _settings: embedder,
    )
    monkeypatch.setattr(
        app_module,
        "make_summarizer",
        lambda _provider, _settings: FakeSummarizer(),
    )

    settings = Settings(_env_file=None, ingest=IngestSettings(max_leaf_docs=100))
    return App(settings), db, embedder


def arrange_corpus(db: MemoryDb) -> None:
    with db.session() as session:
        leaf = Node(
            id=uid(1),
            name="Local relevance corpus",
            description="Deterministic local documents for relevance evaluation.",
            embedding=vector(1.0, 0.0, 0.0),
            kind="leaf",
            status="active",
            doc_count=3,
        )
        docs = [
            Document(
                id=uid(10),
                leaf=leaf,
                source_key="corpus:hydrogen",
                name="Hydrogen Storage Memo",
                summary="Hydrogen pressure storage safety valve memo.",
                body=(
                    "Hydrogen storage requires pressure checks, safety valves, "
                    "and leak response drills."
                ),
                embedding=vector(1.0, 0.0, 0.0),
            ),
            Document(
                id=uid(11),
                leaf=leaf,
                source_key="corpus:payment",
                name="Payment Retry Runbook",
                summary="Payment retry idempotency worker runbook.",
                body=(
                    "Payment workers retry failed charges with idempotency keys "
                    "and durable outbox state."
                ),
                embedding=vector(0.0, 1.0, 0.0),
            ),
            Document(
                id=uid(12),
                leaf=leaf,
                source_key="corpus:semantic",
                name="Semantic Routing Note",
                summary="Semantic vector routing and reference expansion note.",
                body=(
                    "Vector routing finds candidate leaves before scoped hybrid "
                    "search ranks local documents."
                ),
                embedding=vector(0.0, 0.0, 1.0),
            ),
        ]
        session.add_all([leaf, *docs])
        session.commit()


@pytest.mark.asyncio
async def test_relevance_flow_returns_expected_top_results_for_local_queries(
    monkeypatch,
) -> None:
    app, db, embedder = make_app(monkeypatch)
    arrange_corpus(db)

    try:
        cases = [
            ("hydrogen pressure safety", "corpus:hydrogen"),
            ("payment idempotency retry", "corpus:payment"),
            ("semantic vector routing", "corpus:semantic"),
        ]

        for query, expected_source in cases:
            hits = await app.retrieve(query, limit=3)

            assert hits
            assert hits[0].doc.source_key == expected_source
            assert hits[0].bm25 is not None
            assert hits[0].bm25 > 0
            assert hits[0].distance == pytest.approx(0.0)
            assert hits[0].score == pytest.approx(1.0)
            assert all(hit.bm25 is not None for hit in hits)
            assert all(hit.distance is not None for hit in hits)

        assert embedder.calls == [query for query, _expected in cases]
    finally:
        app.close()
