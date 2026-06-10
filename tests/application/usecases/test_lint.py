from __future__ import annotations

from uuid import UUID

import pytest

from application.exceptions import LintDependencyError, MissingUnitOfWork
from application.usecases.lint import Lint
from domain.entity import Node


def uid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012x}")


def node(value: int, *, kind: str = "leaf", status: str = "active") -> Node:
    return Node(
        id=uid(value),
        name=f"Node {value}",
        description=f"Description {value}",
        embedding=[float(value), 0.0],
        kind=kind,
        status=status,
    )


class FakeFullness:
    def __init__(self, threshold: int) -> None:
        self.threshold = threshold
        self.calls: list[int] = []

    def full(self, doc_count: int) -> bool:
        self.calls.append(doc_count)
        return doc_count >= self.threshold


class FakeNodes:
    def __init__(self, item: Node | None, doc_count: int = 0) -> None:
        self.item = item
        self.doc_count = doc_count
        self.get_calls: list[UUID] = []
        self.count_calls: list[UUID] = []

    async def get(self, id: UUID) -> Node | None:
        self.get_calls.append(id)
        return self.item

    async def count(self, id: UUID) -> int:
        self.count_calls.append(id)
        return self.doc_count


class FakeUow:
    def __init__(self, nodes: FakeNodes) -> None:
        self.nodes = nodes
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class FakeSplit:
    def __init__(self) -> None:
        self.calls: list[UUID] = []

    async def run(self, node_id: UUID) -> None:
        self.calls.append(node_id)


def make_case(
    *,
    item: Node | None = None,
    doc_count: int = 0,
    threshold: int = 2,
    split: FakeSplit | None = None,
) -> tuple[Lint, FakeUow, FakeFullness, FakeSplit]:
    nodes = FakeNodes(item, doc_count)
    uow = FakeUow(nodes)
    fullness = FakeFullness(threshold)
    split_case = split or FakeSplit()
    return Lint(uow=uow, split=split_case, fullness=fullness), uow, fullness, split_case


@pytest.mark.asyncio
async def test_lint_requires_unit_of_work() -> None:
    # Arrange
    case = Lint(split=FakeSplit(), fullness=FakeFullness(1))

    # Act / Assert
    with pytest.raises(MissingUnitOfWork, match="UnitOfWork"):
        await case.run(uid(1))


@pytest.mark.asyncio
async def test_lint_requires_split_use_case() -> None:
    # Arrange
    nodes = FakeNodes(node(1), doc_count=2)
    case = Lint(uow=FakeUow(nodes), fullness=FakeFullness(1))

    # Act / Assert
    with pytest.raises(LintDependencyError, match="Split"):
        await case.run(uid(1))


@pytest.mark.asyncio
async def test_lint_requires_fullness_policy() -> None:
    # Arrange
    nodes = FakeNodes(node(1), doc_count=2)
    case = Lint(uow=FakeUow(nodes), split=FakeSplit())

    # Act / Assert
    with pytest.raises(LintDependencyError, match="FullnessPolicy"):
        await case.run(uid(1))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("item", "doc_count"),
    [
        (None, 2),
        (node(1, status="splitting"), 2),
        (node(1, status="retired"), 2),
        (node(1, kind="branch"), 2),
        (node(1), 1),
    ],
)
async def test_lint_skips_stale_or_ineligible_nodes(
    item: Node | None,
    doc_count: int,
) -> None:
    # Arrange
    case, uow, fullness, split = make_case(item=item, doc_count=doc_count, threshold=2)

    # Act
    await case.run(uid(1))

    # Assert
    assert split.calls == []
    assert uow.commits == 0
    if item is None or item.kind != "leaf" or item.status != "active":
        assert fullness.calls == []
        assert uow.nodes.count_calls == []
    else:
        assert fullness.calls == [doc_count]
        assert uow.nodes.count_calls == [item.id]


@pytest.mark.asyncio
async def test_lint_delegates_active_full_leaf_to_split() -> None:
    # Arrange
    leaf = node(1)
    case, uow, fullness, split = make_case(item=leaf, doc_count=3, threshold=2)

    # Act
    await case.run(leaf.id)

    # Assert
    assert fullness.calls == [3]
    assert uow.nodes.count_calls == [leaf.id]
    assert split.calls == [leaf.id]
    assert uow.commits == 0
