from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest

from application.exceptions import RouteDependencyError
from application.ports import NodeHit
from application.usecases.route import Route
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
        name=f"Node {value}",
        description=f"Description {value}",
        embedding=vector(float(value)),
        kind=kind,
        status=status,
    )


@dataclass
class NearCall:
    embedding: list[float]
    limit: int
    parent: UUID | None
    exclude: set[UUID]


class FakeNodes:
    def __init__(
        self,
        root: Node | None = None,
        hits: dict[UUID, list[NodeHit]] | None = None,
    ) -> None:
        self.root_node = root
        self.hits = hits or {}
        self.root_calls = 0
        self.near_calls: list[NearCall] = []

    async def root(self) -> Node | None:
        self.root_calls += 1
        return self.root_node

    async def near(
        self,
        embedding: list[float],
        limit: int,
        parent: UUID | None = None,
        exclude: set[UUID] | None = None,
    ) -> list[NodeHit]:
        seen = set(exclude or set())
        self.near_calls.append(NearCall(embedding, limit, parent, seen))
        hits = self.hits.get(parent, [])
        return [hit for hit in hits if hit.node.id not in seen][:limit]


@pytest.mark.asyncio
async def test_route_raises_application_error_when_nodes_missing() -> None:
    # Arrange
    route = Route()

    # Act / Assert
    with pytest.raises(RouteDependencyError, match="NodeRepo"):
        await route.run(vector(1.0))


@pytest.mark.asyncio
async def test_route_returns_empty_when_limit_is_not_positive() -> None:
    # Arrange
    nodes = FakeNodes(root=node(1))

    # Act
    result = await Route(nodes).run(vector(1.0), limit=0)

    # Assert
    assert result == []
    assert nodes.root_calls == 0
    assert nodes.near_calls == []


@pytest.mark.asyncio
async def test_route_returns_empty_when_root_is_missing() -> None:
    # Arrange
    nodes = FakeNodes()

    # Act
    result = await Route(nodes).run(vector(1.0), limit=3)

    # Assert
    assert result == []
    assert nodes.root_calls == 1
    assert nodes.near_calls == []


@pytest.mark.asyncio
async def test_route_returns_active_root_leaf_with_zero_distance() -> None:
    # Arrange
    root = node(1)
    nodes = FakeNodes(root=root)

    # Act
    result = await Route(nodes).run(vector(1.0), limit=3)

    # Assert
    assert result == [NodeHit(root, 0.0)]
    assert nodes.near_calls == []


@pytest.mark.asyncio
async def test_route_expands_branches_and_orders_limited_leaf_hits() -> None:
    # Arrange
    root = node(1, kind="branch")
    first_branch = node(2, kind="branch")
    second_branch = node(4, kind="branch")
    closest_leaf = node(5)
    tie_leaf = node(6)
    later_tie_leaf = node(8)
    farther_leaf = node(9)
    embedding = vector(0.7)
    nodes = FakeNodes(
        root=root,
        hits={
            root.id: [
                NodeHit(farther_leaf, 0.4),
                NodeHit(second_branch, 0.2),
                NodeHit(first_branch, 0.2),
            ],
            first_branch.id: [
                NodeHit(later_tie_leaf, 0.1),
                NodeHit(tie_leaf, 0.1),
            ],
            second_branch.id: [
                NodeHit(closest_leaf, 0.1),
            ],
        },
    )

    # Act
    result = await Route(nodes).run(embedding, limit=3)

    # Assert
    assert result == [
        NodeHit(closest_leaf, 0.1),
        NodeHit(tie_leaf, 0.1),
        NodeHit(later_tie_leaf, 0.1),
    ]
    assert [call.parent for call in nodes.near_calls] == [
        root.id,
        first_branch.id,
        second_branch.id,
    ]
    assert all(call.embedding is embedding for call in nodes.near_calls)
    assert all(call.limit == 3 for call in nodes.near_calls)
    assert nodes.near_calls[0].exclude == {root.id}
    assert nodes.near_calls[1].exclude == {
        root.id,
        first_branch.id,
        second_branch.id,
        farther_leaf.id,
    }


@pytest.mark.asyncio
async def test_route_passes_seen_ids_to_branch_queries() -> None:
    # Arrange
    root = node(1, kind="branch")
    branch = node(2, kind="branch")
    seen_leaf = node(3)
    new_leaf = node(4)
    nodes = FakeNodes(
        root=root,
        hits={
            root.id: [
                NodeHit(branch, 0.2),
                NodeHit(seen_leaf, 0.3),
            ],
            branch.id: [
                NodeHit(seen_leaf, 0.01),
                NodeHit(new_leaf, 0.1),
            ],
        },
    )

    # Act
    result = await Route(nodes).run(vector(1.0), limit=2)

    # Assert
    assert result == [NodeHit(new_leaf, 0.1), NodeHit(seen_leaf, 0.3)]
    assert nodes.near_calls[1].parent == branch.id
    assert nodes.near_calls[1].exclude == {root.id, branch.id, seen_leaf.id}


@pytest.mark.asyncio
async def test_route_prunes_branch_beam_after_sorting() -> None:
    # Arrange
    root = node(1, kind="branch")
    first_branch = node(2, kind="branch")
    second_branch = node(3, kind="branch")
    dropped_branch = node(4, kind="branch")
    later_closest = node(5, kind="branch")
    later_second = node(6, kind="branch")
    nodes = FakeNodes(
        root=root,
        hits={
            root.id: [
                NodeHit(first_branch, 0.1),
                NodeHit(second_branch, 0.2),
            ],
            first_branch.id: [
                NodeHit(dropped_branch, 0.4),
            ],
            second_branch.id: [
                NodeHit(later_second, 0.02),
                NodeHit(later_closest, 0.01),
            ],
        },
    )

    # Act
    result = await Route(nodes).run(vector(1.0), limit=2)

    # Assert
    assert result == []
    assert [call.parent for call in nodes.near_calls] == [
        root.id,
        first_branch.id,
        second_branch.id,
        later_closest.id,
        later_second.id,
    ]
