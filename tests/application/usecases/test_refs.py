from __future__ import annotations

from uuid import UUID

import pytest

from application.exceptions import MissingUnitOfWork
from application.ports import NodeHit
from application.usecases.refs import Refs
from domain.entity import Node, Reference


def uid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012x}")


def node(
    value: int,
    *,
    kind: str = "leaf",
    status: str = "active",
) -> Node:
    return Node(
        id=uid(value),
        name=f"Node {value}",
        description=f"Description {value}",
        embedding=[float(value), 0.0],
        kind=kind,
        status=status,
    )


class FakeNodes:
    def __init__(self, source: Node | None, hits: list[NodeHit] | None = None) -> None:
        self.source = source
        self.hits = hits or []
        self.got: list[UUID] = []
        self.near_calls: list[tuple[list[float], int, set[UUID] | None]] = []

    async def get(self, id: UUID) -> Node | None:
        self.got.append(id)
        return self.source

    async def near(
        self,
        embedding: list[float],
        limit: int,
        parent: UUID | None = None,
        exclude: set[UUID] | None = None,
    ) -> list[NodeHit]:
        self.near_calls.append((embedding, limit, exclude))
        return self.hits


class FakeRefs:
    def __init__(self) -> None:
        self.replacements: list[tuple[UUID, list[Reference]]] = []

    async def set(self, id: UUID, refs: list[Reference]) -> None:
        self.replacements.append((id, refs))


class FakeUow:
    def __init__(self, source: Node | None, hits: list[NodeHit] | None = None) -> None:
        self.nodes = FakeNodes(source, hits)
        self.refs = FakeRefs()
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_refs_requires_unit_of_work() -> None:
    # Arrange
    refs = Refs()

    # Act / Assert
    with pytest.raises(MissingUnitOfWork, match="UnitOfWork"):
        await refs.run(uid(1))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        None,
        node(1, status="retired"),
        node(1, kind="branch"),
    ],
)
@pytest.mark.parametrize("limit", [10, 0])
async def test_refs_leaves_references_unchanged_when_source_cannot_be_rebuilt(
    source: Node | None,
    limit: int,
) -> None:
    # Arrange
    uow = FakeUow(source)

    # Act
    await Refs(uow).run(uid(1), limit=limit)

    # Assert
    assert uow.nodes.got == [uid(1)]
    assert uow.nodes.near_calls == []
    assert uow.refs.replacements == []
    assert uow.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1])
async def test_refs_replaces_with_empty_list_for_non_positive_limit(limit: int) -> None:
    # Arrange
    source = node(1)
    uow = FakeUow(source)

    # Act
    await Refs(uow).run(source.id, limit=limit)

    # Assert
    assert uow.nodes.near_calls == []
    assert uow.refs.replacements == [(source.id, [])]
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_refs_replaces_outgoing_references_with_ranked_nearest_leaves() -> None:
    # Arrange
    source = node(1)
    first = node(2)
    second = node(3)
    uow = FakeUow(
        source,
        [
            NodeHit(node=first, distance=0.12),
            NodeHit(node=second, distance=0.34),
        ],
    )

    # Act
    await Refs(uow).run(source.id, limit=2)

    # Assert
    assert uow.nodes.near_calls == [(source.embedding, 2, {source.id})]
    assert len(uow.refs.replacements) == 1
    replaced_id, refs = uow.refs.replacements[0]
    assert replaced_id == source.id
    assert [(ref.to_node_id, ref.distance, ref.rank) for ref in refs] == [
        (first.id, 0.12, 0),
        (second.id, 0.34, 1),
    ]
    assert [ref.from_node_id for ref in refs] == [source.id, source.id]
    assert [ref.method for ref in refs] == ["embedding", "embedding"]
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_refs_filters_invalid_candidates_before_ranking() -> None:
    # Arrange
    source = node(1)
    branch = node(2, kind="branch")
    retired = node(3, status="retired")
    self_match = source
    active = node(4)
    uow = FakeUow(
        source,
        [
            NodeHit(node=branch, distance=0.1),
            NodeHit(node=retired, distance=0.2),
            NodeHit(node=self_match, distance=0.3),
            NodeHit(node=active, distance=0.4),
        ],
    )

    # Act
    await Refs(uow).run(source.id, limit=4)

    # Assert
    _, refs = uow.refs.replacements[0]
    assert [(ref.to_node_id, ref.distance, ref.rank) for ref in refs] == [
        (active.id, 0.4, 0),
    ]
    assert refs[0].from_node_id != refs[0].to_node_id
    assert uow.commits == 1
