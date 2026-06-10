from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from application.ports import Search as SearchPort
from domain.entity import Base, Document, Node, Reference, VECTOR_DIMENSIONS
from infrastructure.search import SqlSearch


@pytest.fixture
def search_session() -> Iterator[Session]:
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


def doc(value: int, leaf: Node, *, embedding: list[float]) -> Document:
    return Document(
        id=uid(value),
        leaf=leaf,
        name=f"Doc {value}",
        summary=f"Summary {value}",
        body=f"Body {value}",
        embedding=embedding,
    )


def search(session: Session) -> SqlSearch:
    return SqlSearch(session)


def test_sql_search_satisfies_port(search_session) -> None:
    docs = search(search_session)

    assert isinstance(docs, SearchPort)


@pytest.mark.asyncio
async def test_find_returns_empty_when_scope_or_limit_cannot_return_hits(
    search_session,
) -> None:
    docs = search(search_session)
    leaf = node(1)
    item = doc(2, leaf, embedding=vector(1.0, 0.0))
    search_session.add_all([leaf, item])
    search_session.flush()

    empty_scope = await docs.find("query", vector(1.0, 0.0), set(), limit=10)
    zero_limit = await docs.find("query", vector(1.0, 0.0), {leaf.id}, limit=0)
    negative_limit = await docs.find("query", vector(1.0, 0.0), {leaf.id}, limit=-1)

    assert empty_scope == []
    assert zero_limit == []
    assert negative_limit == []


@pytest.mark.asyncio
async def test_find_scopes_documents_to_supplied_leaves(search_session) -> None:
    docs = search(search_session)
    leaf = node(1)
    other = node(2)
    scoped = doc(3, leaf, embedding=vector(0.0, 1.0))
    excluded = doc(4, other, embedding=vector(1.0, 0.0))
    search_session.add_all([leaf, other, scoped, excluded])
    search_session.flush()

    result = await docs.find("query", vector(1.0, 0.0), {leaf.id}, limit=10)

    assert [hit.doc.id for hit in result] == [scoped.id]


@pytest.mark.asyncio
async def test_find_populates_vector_scores_and_orders_best_first(
    search_session,
) -> None:
    docs = search(search_session)
    leaf = node(1)
    exact = doc(2, leaf, embedding=vector(1.0, 0.0))
    orthogonal = doc(3, leaf, embedding=vector(0.0, 1.0))
    search_session.add_all([leaf, orthogonal, exact])
    search_session.flush()

    result = await docs.find("query", vector(1.0, 0.0), {leaf.id}, limit=10)

    assert [hit.doc.id for hit in result] == [exact.id, orthogonal.id]
    assert result[0].distance == pytest.approx(0.0)
    assert result[0].score == pytest.approx(1.0)
    assert result[0].bm25 is None
    assert result[1].distance == pytest.approx(1.0)
    assert result[1].score == pytest.approx(0.0)
    assert result[1].bm25 is None


@pytest.mark.asyncio
async def test_find_uses_document_id_tie_breaker_and_applies_limit(
    search_session,
) -> None:
    docs = search(search_session)
    leaf = node(1)
    later_tie = doc(5, leaf, embedding=vector(1.0, 0.0))
    farther = doc(4, leaf, embedding=vector(0.0, 1.0))
    first_tie = doc(3, leaf, embedding=vector(1.0, 0.0))
    search_session.add_all([leaf, later_tie, farther, first_tie])
    search_session.flush()

    result = await docs.find("query", vector(1.0, 0.0), {leaf.id}, limit=2)

    assert [hit.doc.id for hit in result] == [first_tie.id, later_tie.id]
