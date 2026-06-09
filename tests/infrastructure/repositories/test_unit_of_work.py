from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from application.ports import UnitOfWork as UnitOfWorkPort
from domain.entity import Base, Document, Job, Node, Reference, VECTOR_DIMENSIONS
from domain.values import JobKind
from infrastructure.repositories.documents import DocumentRepo
from infrastructure.repositories.nodes import NodeRepo
from infrastructure.repositories.outbox import OutboxRepo
from infrastructure.repositories.references import ReferenceRepo
from infrastructure.repositories.unit_of_work import SqlUnitOfWork


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [Node.__table__, Document.__table__, Reference.__table__, Job.__table__]
    Base.metadata.create_all(engine, tables=tables)
    try:
        yield sessionmaker(bind=engine)
    finally:
        Base.metadata.drop_all(engine, tables=tables)
        engine.dispose()


def uid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012x}")


def vector(*values: float) -> list[float]:
    embedding = [0.0] * VECTOR_DIMENSIONS
    for index, value in enumerate(values):
        embedding[index] = value
    return embedding


def node(value: int, *, kind: str = "leaf", parent: Node | None = None) -> Node:
    return Node(
        id=uid(value),
        parent=parent,
        name=f"Node {value}",
        description=f"Description {value}",
        embedding=vector(1.0),
        kind=kind,
    )


def doc(value: int, leaf: Node) -> Document:
    return Document(
        id=uid(value),
        leaf=leaf,
        name=f"Doc {value}",
        summary=f"Summary {value}",
        body=f"Body {value}",
        embedding=vector(1.0),
    )


def reference(value: int, source: Node, target: Node) -> Reference:
    return Reference(
        id=uid(value),
        from_node=source,
        to_node=target,
        distance=0.1,
        rank=0,
    )


def row(session_factory: sessionmaker[Session], model, id: UUID):
    with session_factory() as session:
        return session.get(model, id)


def test_sql_unit_of_work_satisfies_port_and_exposes_repositories(
    sessions,
    now,
) -> None:
    uow = SqlUnitOfWork(sessions, now=lambda: now)
    try:
        assert isinstance(uow, UnitOfWorkPort)
        assert isinstance(uow.nodes, NodeRepo)
        assert isinstance(uow.docs, DocumentRepo)
        assert isinstance(uow.refs, ReferenceRepo)
        assert isinstance(uow.outbox, OutboxRepo)
    finally:
        uow.close()


@pytest.mark.asyncio
async def test_commit_persists_writes_across_repositories(sessions, now) -> None:
    async with SqlUnitOfWork(sessions, now=lambda: now) as uow:
        root = node(1, kind="branch")
        leaf = node(2, parent=root)
        item = doc(3, leaf)
        ref = reference(4, leaf, root)
        job = Job(
            id=uid(5),
            kind=JobKind.SPLIT_CHECK,
            payload={"node_id": str(leaf.id)},
            key=leaf.id,
        )

        await uow.nodes.add(root)
        await uow.nodes.add(leaf)
        await uow.docs.add(item)
        await uow.refs.add(ref)
        await uow.outbox.append(job)

        assert await uow.nodes.count(leaf.id) == 1

        root_id = root.id
        leaf_id = leaf.id
        doc_id = item.id
        ref_id = ref.id
        job_id = job.id
        await uow.commit()

    assert row(sessions, Node, root_id).name == "Node 1"
    assert row(sessions, Node, leaf_id).parent_id == root_id
    assert row(sessions, Document, doc_id).leaf_id == leaf_id
    assert row(sessions, Reference, ref_id).from_node_id == leaf_id
    assert row(sessions, Job, job_id).key == leaf_id


@pytest.mark.asyncio
async def test_rollback_discards_pending_repository_writes(sessions, now) -> None:
    uow = SqlUnitOfWork(sessions, now=lambda: now)
    leaf = node(1)
    job = Job(
        id=uid(2),
        kind=JobKind.SPLIT_CHECK,
        payload={"node_id": str(leaf.id)},
        key=leaf.id,
    )
    try:
        await uow.nodes.add(leaf)
        await uow.outbox.append(job)

        await uow.rollback()
    finally:
        uow.close()

    assert row(sessions, Node, leaf.id) is None
    assert row(sessions, Job, job.id) is None


@pytest.mark.asyncio
async def test_context_rolls_back_on_exception(sessions, now) -> None:
    leaf = node(1)

    with pytest.raises(ValueError):
        async with SqlUnitOfWork(sessions, now=lambda: now) as uow:
            await uow.nodes.add(leaf)

            raise ValueError("stop")

    assert row(sessions, Node, leaf.id) is None


@pytest.mark.asyncio
async def test_context_rolls_back_without_commit(sessions, now) -> None:
    leaf = node(1)

    async with SqlUnitOfWork(sessions, now=lambda: now) as uow:
        await uow.nodes.add(leaf)

    assert row(sessions, Node, leaf.id) is None


@pytest.mark.asyncio
async def test_clean_read_context_returns_loaded_detached_objects(sessions, now) -> None:
    leaf = node(1)
    leaf_id = leaf.id
    with sessions() as session:
        session.add(leaf)
        session.commit()

    async with SqlUnitOfWork(sessions, now=lambda: now) as uow:
        loaded = await uow.nodes.get(leaf_id)
        assert loaded is not None

    assert loaded.name == "Node 1"
    assert loaded.description == "Description 1"


@pytest.mark.asyncio
async def test_reused_unit_of_work_opens_session_per_context_scope(sessions, now) -> None:
    shared = SqlUnitOfWork(sessions, now=lambda: now)

    async with shared as first:
        async with shared as second:
            assert first.session is not second.session
            assert first.nodes is not second.nodes

        await first.nodes.add(node(1))
        await first.commit()

    assert row(sessions, Node, uid(1)).name == "Node 1"
