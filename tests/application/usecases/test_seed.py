from __future__ import annotations

from uuid import UUID

import pytest

from application.exceptions import MissingUnitOfWork
from application.usecases.seed import Seed
from domain.entity import VECTOR_DIMENSIONS, Node


def uid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012x}")


def vector(*values: float) -> list[float]:
    embedding = [0.0] * VECTOR_DIMENSIONS
    for index, value in enumerate(values):
        embedding[index] = value
    return embedding


def node(value: int, *, kind: str = "leaf", status: str = "active") -> Node:
    return Node(
        id=uid(value),
        parent_id=None,
        name=f"Node {value}",
        description=f"Description {value}",
        embedding=vector(float(value)),
        kind=kind,
        status=status,
    )


class FakeNodes:
    def __init__(self, root: Node | None = None) -> None:
        self.root_node = root
        self.root_calls = 0
        self.added: list[Node] = []

    async def root(self) -> Node | None:
        self.root_calls += 1
        return self.root_node

    async def add(self, node: Node) -> UUID:
        self.added.append(node)
        self.root_node = node
        return node.id


class FakeUow:
    def __init__(self, root: Node | None = None) -> None:
        self.nodes = FakeNodes(root)
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_seed_requires_unit_of_work() -> None:
    # Arrange
    seed = Seed()

    # Act / Assert
    with pytest.raises(MissingUnitOfWork, match="UnitOfWork"):
        await seed.run()


@pytest.mark.asyncio
async def test_seed_returns_existing_root_without_creating_duplicate() -> None:
    # Arrange
    root = node(1, kind="branch")
    uow = FakeUow(root)

    # Act
    result = await Seed(uow).run()

    # Assert
    assert result is root
    assert uow.nodes.root_calls == 1
    assert uow.nodes.added == []
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_seed_creates_active_leaf_root_when_missing() -> None:
    # Arrange
    uow = FakeUow()

    # Act
    result = await Seed(uow).run()

    # Assert
    assert result is uow.nodes.added[0]
    assert uow.nodes.root_calls == 1
    assert uow.commits == 1
    assert result.parent_id is None
    assert result.name == "Root"
    assert result.description == "Stable root for the Alexandria semantic index."
    assert result.kind == "leaf"
    assert result.status == "active"
    assert result.doc_count == 0
    assert result.version == 1
    assert len(result.embedding) == VECTOR_DIMENSIONS
    assert result.embedding == vector(1.0)


@pytest.mark.asyncio
async def test_seed_does_not_create_duplicate_root_on_later_run() -> None:
    # Arrange
    uow = FakeUow()
    seed = Seed(uow)

    # Act
    created = await seed.run()
    returned = await seed.run()

    # Assert
    assert returned is created
    assert uow.nodes.root_calls == 2
    assert uow.nodes.added == [created]
    assert uow.commits == 1
