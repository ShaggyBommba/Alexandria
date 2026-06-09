from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from application.ports import DocumentRepo as DocumentPort
from domain.entity import Base, Document, Node, Reference, VECTOR_DIMENSIONS
from infrastructure.repositories.documents import DocumentRepo


@pytest.fixture
def doc_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [Node.__table__, Document.__table__, Reference.__table__]
    Base.metadata.create_all(engine, tables=tables)
    try:
        with Session(engine) as session:
            yield session
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


def node(value: int) -> Node:
    return Node(
        id=uid(value),
        name=f"Node {value}",
        description=f"Description {value}",
        embedding=vector(1.0),
    )


def doc(
    value: int,
    leaf: Node,
    *,
    name: str | None = None,
    source_key: str | None = None,
) -> Document:
    return Document(
        id=uid(value),
        leaf=leaf,
        source_key=source_key,
        name=name or f"Doc {value}",
        summary=f"Summary {value}",
        body=f"Body {value}",
        embedding=vector(1.0),
    )


def repo(session: Session) -> DocumentRepo:
    return DocumentRepo(session)


def test_document_repo_satisfies_port(doc_session) -> None:
    docs = repo(doc_session)

    assert isinstance(docs, DocumentPort)


@pytest.mark.asyncio
async def test_add_persists_document_and_get_returns_it(doc_session) -> None:
    docs = repo(doc_session)
    leaf = node(1)
    item = doc(2, leaf, source_key="source:2")
    doc_session.add(leaf)
    doc_session.flush()

    id = await docs.add(item)

    saved = await docs.get(id)
    assert id == uid(2)
    assert saved is item
    assert saved.leaf_id == leaf.id
    assert saved.source_key == "source:2"
    assert saved.name == "Doc 2"
    assert list(saved.embedding[:1]) == pytest.approx([1.0])


@pytest.mark.asyncio
async def test_leaf_returns_documents_attached_to_leaf(doc_session) -> None:
    docs = repo(doc_session)
    leaf = node(1)
    other = node(2)
    first = doc(3, leaf)
    second = doc(4, leaf)
    unrelated = doc(5, other)
    doc_session.add_all([leaf, other, first, second, unrelated])
    doc_session.flush()

    result = await docs.leaf(leaf.id)

    assert [item.id for item in result] == [first.id, second.id]


@pytest.mark.asyncio
async def test_move_reassigns_documents_and_ignores_missing_rows(doc_session) -> None:
    docs = repo(doc_session)
    source = node(1)
    target = node(2)
    moving = doc(3, source)
    staying = doc(4, source)
    doc_session.add_all([source, target, moving, staying])
    doc_session.flush()

    await docs.move([moving.id, uid(99)], target.id)
    await docs.move([], target.id)
    doc_session.expire_all()

    moved = await docs.get(moving.id)
    kept = await docs.get(staying.id)
    assert moved.leaf_id == target.id
    assert kept.leaf_id == source.id


@pytest.mark.asyncio
async def test_save_persists_document_changes(doc_session) -> None:
    docs = repo(doc_session)
    leaf = node(1)
    item = doc(2, leaf)
    doc_session.add_all([leaf, item])
    doc_session.flush()

    item.summary = "Updated summary"
    item.body = "Updated body"
    await docs.save(item)
    doc_session.expire_all()

    saved = await docs.get(item.id)
    assert saved.summary == "Updated summary"
    assert saved.body == "Updated body"


@pytest.mark.asyncio
async def test_rm_deletes_document_and_ignores_missing_rows(doc_session) -> None:
    docs = repo(doc_session)
    leaf = node(1)
    item = doc(2, leaf)
    doc_session.add_all([leaf, item])
    doc_session.flush()

    await docs.rm(item.id)
    await docs.rm(uid(99))

    assert await docs.get(item.id) is None
