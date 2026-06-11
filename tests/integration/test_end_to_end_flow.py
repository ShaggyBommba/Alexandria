from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from application.app import App
import application.app as app_module
from application.ports import ChildPlan, DocIn, SplitPlan
from domain.entity import Base, Document, Job, Node, VECTOR_DIMENSIONS
from domain.values import JobKind, JobStatus
from infrastructure.config import IngestSettings, Settings
from presentation.worker.app import Worker


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

    def close(self) -> None:
        self._engine.dispose()


class FakeEmbedder:
    def __init__(self, embed: Callable[[str], list[float]]) -> None:
        self.embed_text = embed
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return self.embed_text(text)


class FakeSummarizer:
    def __init__(self) -> None:
        self.calls: list[DocIn] = []

    async def summarize(self, doc: DocIn) -> str:
        self.calls.append(doc)
        return f"Summary for {doc.name}."


class DeterministicSplitter:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, list[UUID]]] = []

    async def split(self, node: Node, docs: list[Document]) -> SplitPlan:
        ordered = sorted(docs, key=lambda item: item.name)
        self.calls.append((node.id, [doc.id for doc in ordered]))
        return SplitPlan(
            children=[
                ChildPlan(
                    name="Alpha lifecycle",
                    description="Documents about alpha lifecycle work.",
                    embedding=vector(1.0, 0.0),
                    docs=[ordered[0].id, ordered[2].id],
                ),
                ChildPlan(
                    name="Beta operations",
                    description="Documents about beta operations.",
                    embedding=vector(0.0, 1.0),
                    docs=[ordered[1].id],
                ),
            ]
        )


def vector(*values: float) -> list[float]:
    embedding = [0.0] * VECTOR_DIMENSIONS
    for index, value in enumerate(values):
        embedding[index] = value
    return embedding


def deterministic_embedding(text: str) -> list[float]:
    lowered = text.lower()
    if "beta" in lowered:
        return vector(0.0, 1.0)
    if "alpha" in lowered:
        return vector(1.0, 0.0)
    return vector(0.0, 0.0, 1.0)


def sources(hits) -> list[str | None]:
    return [hit.doc.source_key for hit in hits]


@pytest.mark.asyncio
async def test_end_to_end_local_lifecycle_ingests_retrieves_splits_and_retrieves(
    monkeypatch,
) -> None:
    # Arrange
    db = MemoryDb()
    embedder = FakeEmbedder(deterministic_embedding)
    summarizer = FakeSummarizer()
    splitter = DeterministicSplitter()

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

    settings = Settings(_env_file=None, ingest=IngestSettings(max_leaf_docs=3))
    docs = [
        DocIn(
            name="Alpha",
            body="Alpha local lifecycle notes about setup, routing, and retrieval.",
            source_key="source:alpha",
        ),
        DocIn(
            name="Beta",
            body="Beta operations note about queue workers and retries.",
            source_key="source:beta",
        ),
        DocIn(
            name="Gamma",
            body="Gamma archive note for the split lifecycle.",
            source_key="source:gamma",
        ),
    ]

    app = App(settings, splitter=splitter)
    try:
        # Act: initialize, ingest, and retrieve before maintenance work runs.
        root = await app.seed()
        assert root.kind == "leaf"
        assert root.status == "active"
        ids = [await app.ingest(doc) for doc in docs]
        before_split = await app.retrieve("alpha local lifecycle", limit=3)
        processed = await Worker(app=app, kind=JobKind.SPLIT_CHECK).batch()
        app.session.expire_all()
        after_split = await app.retrieve("alpha local lifecycle", limit=1)

        # Assert: seed and ingest built a full root leaf and queued split work.
        assert sources(before_split)[0] == "source:alpha"
        assert {hit.doc.id for hit in before_split} >= set(ids[:2])
        assert processed == 1

        with db.session() as session:
            saved_root = session.scalar(
                select(Node).where(Node.parent_id.is_(None))
            )
            assert saved_root is not None
            assert saved_root.kind == "branch"
            assert saved_root.status == "active"
            assert saved_root.doc_count == 0
            assert saved_root.version == 2

            children = session.scalars(
                select(Node)
                .where(Node.parent_id == saved_root.id)
                .order_by(Node.name.asc())
            ).all()
            assert [
                (child.name, child.kind, child.status, child.doc_count)
                for child in children
            ] == [
                ("Alpha lifecycle", "leaf", "active", 2),
                ("Beta operations", "leaf", "active", 1),
            ]

            docs_by_source = {
                doc.source_key: doc
                for doc in session.scalars(select(Document)).all()
            }
            children_by_name = {child.name: child for child in children}
            assert docs_by_source["source:alpha"].leaf_id == children_by_name[
                "Alpha lifecycle"
            ].id
            assert docs_by_source["source:gamma"].leaf_id == children_by_name[
                "Alpha lifecycle"
            ].id
            assert docs_by_source["source:beta"].leaf_id == children_by_name[
                "Beta operations"
            ].id

            job = session.scalar(select(Job).where(Job.kind == JobKind.SPLIT_CHECK))
            assert job is not None
            assert job.key == saved_root.id
            assert job.status == JobStatus.DONE.value
            assert job.done_at is not None
            assert job.last_error is None

        assert splitter.calls == [(root.id, ids)]
        assert sources(after_split) == ["source:alpha"]
        assert "alpha local lifecycle" in embedder.calls
        assert summarizer.calls == docs
    finally:
        app.close()
