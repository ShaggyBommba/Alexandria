from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from application.app import App
import application.app as app_module
from application.ports import DocIn
from domain.entity import Base, Document, Node, Reference, VECTOR_DIMENSIONS
from infrastructure.config import IngestSettings, Settings


class MemoryDb:
    def __init__(self) -> None:
        self._engine = create_engine("sqlite+pysqlite:///:memory:")
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
    def __init__(self, summaries: dict[str, str]) -> None:
        self.summaries = summaries
        self.calls: list[DocIn] = []

    async def summarize(self, doc: DocIn) -> str:
        self.calls.append(doc)
        return self.summaries[doc.name]


def uid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012x}")


def vector(*values: float) -> list[float]:
    embedding = [0.0] * VECTOR_DIMENSIONS
    for index, value in enumerate(values):
        embedding[index] = value
    return embedding


def deterministic_embedding(text: str) -> list[float]:
    lowered = text.lower()
    if "beta" in lowered:
        return vector(0.0, 1.0)
    if "reference target" in lowered:
        return vector(1.0, 0.0)
    if "alpha" in lowered:
        return vector(1.0, 0.0)
    return vector(0.0, 0.0, 1.0)


def make_app(monkeypatch) -> tuple[App, MemoryDb, FakeEmbedder, FakeSummarizer]:
    db = MemoryDb()
    embedder = FakeEmbedder(deterministic_embedding)
    summarizer = FakeSummarizer(
        {
            "Alpha": "Alpha summary.",
            "Beta": "Beta summary.",
        }
    )

    monkeypatch.setattr(app_module, "Db", lambda _settings: db)
    monkeypatch.setattr(
        app_module,
        "make_embedder",
        lambda _provider, _settings: embedder,
    )
    monkeypatch.setattr(
        app_module,
        "make_summarizer",
        lambda _provider, _settings: summarizer,
    )

    settings = Settings(_env_file=None, ingest=IngestSettings(max_leaf_docs=100))
    return App(settings), db, embedder, summarizer


@pytest.mark.asyncio
async def test_retrieve_flow_returns_locally_ingested_documents(monkeypatch) -> None:
    # Arrange
    app, _db, embedder, summarizer = make_app(monkeypatch)
    alpha = DocIn(
        name="Alpha",
        body="alpha retrieval notes",
        source_key="source:alpha",
    )
    beta = DocIn(
        name="Beta",
        body="beta retrieval notes",
        source_key="source:beta",
    )

    # Act
    alpha_id = await app.ingest(alpha)
    beta_id = await app.ingest(beta)
    hits = await app.retrieve("alpha retrieval query", limit=2)

    # Assert
    assert [hit.doc.id for hit in hits] == [alpha_id, beta_id]
    assert [hit.doc.source_key for hit in hits] == ["source:alpha", "source:beta"]
    assert [hit.doc.name for hit in hits] == ["Alpha", "Beta"]
    assert hits[0].score == pytest.approx(0.4)
    assert hits[0].distance == pytest.approx(0.0)
    assert hits[0].bm25 is not None
    assert hits[1].score < hits[0].score
    assert hits[1].distance == pytest.approx(1.0)
    assert hits[1].bm25 is not None
    assert "alpha retrieval query" in embedder.calls
    assert summarizer.calls == [alpha, beta]


@pytest.mark.asyncio
async def test_retrieve_flow_expands_scope_through_references(monkeypatch) -> None:
    # Arrange
    app, db, _embedder, _summarizer = make_app(monkeypatch)
    root_id = uid(1)
    source_leaf_id = uid(2)
    target_leaf_id = uid(3)
    source_doc_id = uid(10)
    target_doc_id = uid(11)

    with db.session() as session:
        root = Node(
            id=root_id,
            name="Root",
            description="Root branch",
            embedding=vector(1.0, 0.0),
            kind="branch",
        )
        source_leaf = Node(
            id=source_leaf_id,
            parent=root,
            name="Source",
            description="Routed source leaf",
            embedding=vector(1.0, 0.0),
            kind="leaf",
            doc_count=1,
        )
        target_leaf = Node(
            id=target_leaf_id,
            parent=root,
            name="Target",
            description="Referenced target leaf",
            embedding=vector(1.0, 0.0),
            kind="leaf",
            doc_count=1,
        )
        source_doc = Document(
            id=source_doc_id,
            leaf=source_leaf,
            source_key="source:source",
            name="Source Doc",
            summary="Source summary",
            body="Source body",
            embedding=vector(0.0, 1.0),
        )
        target_doc = Document(
            id=target_doc_id,
            leaf=target_leaf,
            source_key="source:target",
            name="Target Doc",
            summary="Target summary",
            body="Target body",
            embedding=vector(1.0, 0.0),
        )
        ref = Reference(
            id=uid(20),
            from_node=source_leaf,
            to_node=target_leaf,
            distance=0.0,
            rank=0,
        )
        session.add_all([root, source_leaf, target_leaf, source_doc, target_doc, ref])
        session.commit()

    # Act
    routed = await app.route(vector(1.0, 0.0), limit=1)
    hits = await app.retrieve("reference target query", limit=1)

    # Assert
    assert [hit.node.id for hit in routed] == [source_leaf_id]
    assert [hit.doc.id for hit in hits] == [target_doc_id]
    assert hits[0].doc.source_key == "source:target"
    assert hits[0].score == pytest.approx(0.4)
    assert hits[0].distance == pytest.approx(0.0)
    assert hits[0].bm25 is not None
