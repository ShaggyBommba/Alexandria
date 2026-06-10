from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from application.ports import NodeRepo as NodePort
from domain.entity import Base, Document, Node, Reference, VECTOR_DIMENSIONS
from infrastructure.repositories.nodes import NodeRepo


@pytest.fixture
def node_session() -> Iterator[Session]:
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


def node(
    value: int,
    *,
    parent: Node | None = None,
    embedding: list[float] | None = None,
    kind: str = "leaf",
    status: str = "active",
) -> Node:
    return Node(
        id=uid(value),
        parent=parent,
        name=f"Node {value}",
        description=f"Description {value}",
        embedding=embedding or vector(1.0),
        kind=kind,
        status=status,
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


def repo(session: Session) -> NodeRepo:
    return NodeRepo(session)


def test_node_repo_satisfies_port(node_session) -> None:
    nodes = repo(node_session)

    assert isinstance(nodes, NodePort)


@pytest.mark.asyncio
async def test_add_persists_node_and_get_returns_it(node_session) -> None:
    nodes = repo(node_session)
    root = node(1, kind="branch")

    id = await nodes.add(root)

    saved = await nodes.get(id)
    assert id == uid(1)
    assert saved is root
    assert saved.name == "Node 1"
    assert list(saved.embedding[:1]) == pytest.approx([1.0])


@pytest.mark.asyncio
async def test_root_returns_active_parentless_node(node_session) -> None:
    nodes = repo(node_session)
    retired = node(1, kind="branch", status="retired")
    active = node(2, kind="branch")
    child = node(3, parent=active)
    node_session.add_all([retired, active, child])
    node_session.flush()

    result = await nodes.root()

    assert result is active


@pytest.mark.asyncio
async def test_kids_returns_direct_children(node_session) -> None:
    nodes = repo(node_session)
    root = node(1, kind="branch")
    child = node(2, parent=root)
    grandchild = node(3, parent=child)
    sibling = node(4, parent=root, status="retired")
    node_session.add_all([root, child, grandchild, sibling])
    node_session.flush()

    result = await nodes.kids(root.id)

    assert [item.id for item in result] == [child.id, sibling.id]


@pytest.mark.asyncio
async def test_leaves_returns_active_leaves_with_limit(node_session) -> None:
    nodes = repo(node_session)
    root = node(1, kind="branch")
    first = node(2, parent=root)
    second = node(3, parent=root)
    retired = node(4, parent=root, status="retired")
    node_session.add_all([root, first, second, retired])
    node_session.flush()

    result = await nodes.leaves(limit=1)

    assert [item.id for item in result] == [first.id]


@pytest.mark.asyncio
async def test_near_filters_and_orders_nodes_by_deterministic_distance(
    node_session,
) -> None:
    nodes = repo(node_session)
    root = node(1, kind="branch")
    exact_later = node(5, parent=root, embedding=vector(1.0, 0.0))
    excluded = node(2, parent=root, embedding=vector(1.0, 0.0))
    exact_first = node(3, parent=root, embedding=vector(1.0, 0.0))
    farther = node(4, parent=root, embedding=vector(0.0, 1.0))
    retired = node(6, parent=root, embedding=vector(1.0, 0.0), status="retired")
    other_parent = node(7, embedding=vector(1.0, 0.0))
    node_session.add_all(
        [root, exact_later, excluded, exact_first, farther, retired, other_parent]
    )
    node_session.flush()

    result = await nodes.near(
        vector(1.0, 0.0),
        limit=2,
        parent=root.id,
        exclude={excluded.id},
    )

    assert [hit.node.id for hit in result] == [exact_first.id, exact_later.id]
    assert [hit.distance for hit in result] == [pytest.approx(0.0), pytest.approx(0.0)]


@pytest.mark.asyncio
async def test_near_returns_empty_for_non_positive_limit(node_session) -> None:
    nodes = repo(node_session)
    root = node(1, kind="branch")
    child = node(2, parent=root)
    node_session.add_all([root, child])
    node_session.flush()

    zero = await nodes.near(vector(1.0), limit=0, parent=root.id)
    negative = await nodes.near(vector(1.0), limit=-1, parent=root.id)

    assert zero == []
    assert negative == []


@pytest.mark.asyncio
async def test_count_returns_documents_attached_to_node(node_session) -> None:
    nodes = repo(node_session)
    leaf = node(1)
    other = node(2)
    node_session.add_all([leaf, other, doc(3, leaf), doc(4, leaf), doc(5, other)])
    node_session.flush()

    result = await nodes.count(leaf.id)

    assert result == 2


@pytest.mark.asyncio
async def test_save_persists_node_changes(node_session) -> None:
    nodes = repo(node_session)
    leaf = node(1)
    node_session.add(leaf)
    node_session.flush()

    leaf.description = "Updated description"
    await nodes.save(leaf)
    node_session.expire_all()

    saved = await nodes.get(leaf.id)
    assert saved.description == "Updated description"


@pytest.mark.asyncio
async def test_rm_deletes_node_and_ignores_missing_rows(node_session) -> None:
    nodes = repo(node_session)
    leaf = node(1)
    node_session.add(leaf)
    node_session.flush()

    await nodes.rm(leaf.id)
    await nodes.rm(uid(99))

    assert await nodes.get(leaf.id) is None
