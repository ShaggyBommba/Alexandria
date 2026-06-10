from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from application.app import App
import application.app as app_module
from application.ports import DocIn
from domain.entity import Base, Document, Job, Node, VECTOR_DIMENSIONS
from domain.values import JobKind
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
    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return self.embedding


def deterministic_embedding() -> list[float]:
    values = [0.0] * VECTOR_DIMENSIONS
    values[0] = 0.1
    values[1] = 0.2
    values[2] = 0.3
    return values


class FakeSummarizer:
    def __init__(self, summaries: dict[str, str]) -> None:
        self.summaries = summaries
        self.calls: list[DocIn] = []

    async def summarize(self, doc: DocIn) -> str:
        self.calls.append(doc)
        return self.summaries[doc.name]


@pytest.mark.asyncio
async def test_ingest_smoke_appends_split_check_when_leaf_is_full(monkeypatch) -> None:
    # Arrange
    db = MemoryDb()
    fake_summarizer = FakeSummarizer(
        {
            "Alpha": "Concise alpha summary.",
            "Beta": "Concise beta summary.",
        }
    )

    monkeypatch.setattr(app_module, "Db", lambda _settings: db)
    monkeypatch.setattr(
        app_module,
        "make_embedder",
        lambda _provider, _settings: FakeEmbedder(deterministic_embedding()),
    )
    monkeypatch.setattr(app_module, "make_summarizer", lambda _provider, _settings: fake_summarizer)

    settings = Settings(_env_file=None, ingest=IngestSettings(max_leaf_docs=2))
    app = App(settings)

    docs = [
        DocIn(name="Alpha", body="first body", source_key="source:alpha"),
        DocIn(name="Beta", body="second body", source_key="source:beta"),
    ]

    # Act
    first_id = await app.ingest(docs[0])
    second_id = await app.ingest(docs[1])

    # Assert
    with db.session() as session:
        root = session.scalar(
            select(Node).where(
                Node.parent_id.is_(None),
                Node.kind == "leaf",
                Node.status == "active",
            )
        )
        assert root is not None
        assert root.doc_count == 2

        leaf_documents = session.scalars(
            select(Document).where(Document.leaf_id == root.id).order_by(Document.name.asc())
        ).all()
        assert len(leaf_documents) == 2

        by_source: dict[str, Document] = {
            document.source_key: document for document in leaf_documents if document.source_key is not None
        }

        first_doc = by_source["source:alpha"]
        assert first_doc.id == first_id
        assert first_doc.name == "Alpha"
        assert first_doc.body == "first body"
        assert first_doc.source_key == "source:alpha"
        assert first_doc.summary == "Concise alpha summary."
        assert list(first_doc.embedding) == deterministic_embedding()

        second_doc = by_source["source:beta"]
        assert second_doc.id == second_id
        assert second_doc.name == "Beta"
        assert second_doc.body == "second body"
        assert second_doc.source_key == "source:beta"
        assert second_doc.summary == "Concise beta summary."
        assert list(second_doc.embedding) == deterministic_embedding()

        split_jobs = session.scalars(
            select(Job).where(Job.kind == JobKind.SPLIT_CHECK.value)
        ).all()
        assert len(split_jobs) == 1
        split_job = split_jobs[0]
        assert split_job.key == root.id
        assert split_job.payload == {"node_id": str(root.id)}

        assert fake_summarizer.calls == docs
