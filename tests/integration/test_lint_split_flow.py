from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from application.app import App
import application.app as app_module
from application.ports import ChildPlan, DocIn, SplitPlan
from domain.entity import Base, Document, Job, Node, Reference, VECTOR_DIMENSIONS
from domain.values import JobKind, JobStatus
from infrastructure.config import IngestSettings, Settings
from infrastructure.repositories.outbox import OutboxRepo
from presentation.worker.app import Worker


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
    async def embed(self, text: str) -> list[float]:
        return vector(float(len(text)))


class FakeSummarizer:
    async def summarize(self, doc: DocIn) -> str:
        return f"summary:{doc.name}"


class DeterministicSplitter:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, list[UUID]]] = []

    async def split(self, node: Node, docs: list[Document]) -> SplitPlan:
        ordered = sorted(docs, key=lambda item: item.name)
        self.calls.append((node.id, [doc.id for doc in ordered]))
        return SplitPlan(
            children=[
                ChildPlan(
                    name="Alpha child",
                    description="Documents about alpha topics.",
                    embedding=vector(0.1),
                    docs=[ordered[0].id, ordered[2].id],
                ),
                ChildPlan(
                    name="Beta child",
                    description="Documents about beta topics.",
                    embedding=vector(0.2),
                    docs=[ordered[1].id],
                ),
            ]
        )


def uid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012x}")


def vector(*values: float) -> list[float]:
    embedding = [0.0] * VECTOR_DIMENSIONS
    for index, value in enumerate(values):
        embedding[index] = value
    return embedding


def make_doc(value: int, leaf: Node, name: str) -> Document:
    return Document(
        id=uid(value),
        leaf=leaf,
        source_key=f"source:{value}",
        name=name,
        summary=f"Summary {name}",
        body=f"Body {name}",
        embedding=vector(float(value)),
    )


@pytest.mark.asyncio
async def test_worker_lint_splits_full_leaf_and_marks_job_done(monkeypatch) -> None:
    # Arrange
    db = MemoryDb()
    splitter = DeterministicSplitter()

    monkeypatch.setattr(app_module, "Db", lambda _settings: db)
    monkeypatch.setattr(app_module, "make_embedder", lambda _provider, _settings: FakeEmbedder())
    monkeypatch.setattr(
        app_module,
        "make_summarizer",
        lambda _provider, _settings: FakeSummarizer(),
    )

    settings = Settings(_env_file=None, ingest=IngestSettings(max_leaf_docs=2))
    app = App(settings, splitter=splitter)

    with db.session() as session:
        source = Node(
            id=uid(1),
            name="Source",
            description="Full source leaf.",
            embedding=vector(1.0),
            kind="leaf",
            status="active",
            doc_count=3,
        )
        target = Node(
            id=uid(2),
            name="Target",
            description="Referenced target leaf.",
            embedding=vector(2.0),
            kind="leaf",
            status="active",
        )
        docs = [
            make_doc(10, source, "Alpha"),
            make_doc(11, source, "Beta"),
            make_doc(12, source, "Gamma"),
        ]
        stale_ref = Reference(
            id=uid(20),
            from_node=source,
            to_node=target,
            distance=0.2,
            rank=0,
        )
        session.add_all([source, target, *docs, stale_ref])
        session.flush()

        outbox = OutboxRepo(session, settings.queue)
        job_id = await outbox.append(
            Job(
                kind=JobKind.SPLIT_CHECK,
                payload={"node_id": str(source.id)},
                key=source.id,
            )
        )
        session.commit()

    # Act
    processed = await Worker(app=app, kind=JobKind.SPLIT_CHECK).batch()

    # Assert
    with db.session() as session:
        saved_source = session.get(Node, uid(1))
        assert saved_source is not None
        assert processed == 1
        assert saved_source.kind == "branch"
        assert saved_source.status == "active"
        assert saved_source.doc_count == 0
        assert saved_source.version == 2

        children = session.scalars(
            select(Node)
            .where(Node.parent_id == saved_source.id)
            .order_by(Node.name.asc())
        ).all()
        assert [(child.name, child.kind, child.status, child.doc_count) for child in children] == [
            ("Alpha child", "leaf", "active", 2),
            ("Beta child", "leaf", "active", 1),
        ]

        moved = session.scalars(
            select(Document).order_by(Document.name.asc())
        ).all()
        by_name = {doc.name: doc.leaf_id for doc in moved}
        by_child_name = {child.name: child.id for child in children}
        assert by_name == {
            "Alpha": by_child_name["Alpha child"],
            "Beta": by_child_name["Beta child"],
            "Gamma": by_child_name["Alpha child"],
        }
        assert all(doc.leaf_id != saved_source.id for doc in moved)

        stale_refs = session.scalars(
            select(Reference).where(Reference.from_node_id == saved_source.id)
        ).all()
        assert stale_refs == []

        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.DONE.value
        assert job.done_at is not None
        assert job.last_error is None

    assert splitter.calls == [(uid(1), [uid(10), uid(11), uid(12)])]
