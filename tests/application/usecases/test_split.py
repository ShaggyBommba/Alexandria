from __future__ import annotations

from uuid import UUID

import pytest

from application.exceptions import (
    MissingUnitOfWork,
    SplitDependencyError,
    SplitPlanError,
)
from application.ports import ChildPlan, SplitPlan
from application.usecases.split import Split
from domain.entity import Document, Node


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


def doc(value: int, leaf: Node) -> Document:
    return Document(
        id=uid(value),
        leaf_id=leaf.id,
        source_key=f"source:{value}",
        name=f"Doc {value}",
        summary=f"Summary {value}",
        body=f"Body {value}",
        embedding=[float(value), 0.0],
    )


def child(name: str, docs: list[UUID]) -> ChildPlan:
    return ChildPlan(
        name=name,
        description=f"{name} description",
        embedding=[1.0, 0.0],
        docs=docs,
    )


class FakeFullness:
    def __init__(self, threshold: int) -> None:
        self.threshold = threshold
        self.calls: list[int] = []

    def full(self, doc_count: int) -> bool:
        self.calls.append(doc_count)
        return doc_count >= self.threshold


class FakeSplitter:
    def __init__(self, plan: SplitPlan, events: list[str] | None = None) -> None:
        self.plan = plan
        self.events = events
        self.calls: list[tuple[Node, list[Document]]] = []

    async def split(self, node: Node, docs: list[Document]) -> SplitPlan:
        if self.events is not None:
            self.events.append("split")
        self.calls.append((node, docs))
        return self.plan


class FakeNodes:
    def __init__(self, source: Node, events: list[str]) -> None:
        self.source = source
        self.events = events
        self.added: list[Node] = []
        self.saved: list[Node] = []
        self.saved_states: list[tuple[str, str, int]] = []

    async def get(self, id: UUID) -> Node | None:
        self.events.append("get_node")
        if id == self.source.id:
            return self.source
        return None

    async def add(self, item: Node) -> UUID:
        self.events.append("add_node")
        self.added.append(item)
        return item.id

    async def save(self, item: Node) -> None:
        self.events.append("save_node")
        self.saved.append(item)
        self.saved_states.append((item.kind, item.status, item.doc_count))


class FakeDocs:
    def __init__(self, docs: list[Document], events: list[str]) -> None:
        self.docs = docs
        self.events = events
        self.moves: list[tuple[list[UUID], UUID]] = []

    async def leaf(self, id: UUID) -> list[Document]:
        self.events.append("leaf_docs")
        return [doc for doc in self.docs if doc.leaf_id == id]

    async def move(self, ids: list[UUID], leaf: UUID) -> None:
        self.events.append("move_docs")
        self.moves.append((ids, leaf))
        move_ids = set(ids)
        for item in self.docs:
            if item.id in move_ids:
                item.leaf_id = leaf


class FakeRefs:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.cleared: list[UUID] = []

    async def clear(self, id: UUID) -> None:
        self.events.append("clear_refs")
        self.cleared.append(id)


class FakeUow:
    def __init__(self, source: Node, docs: list[Document], events: list[str]) -> None:
        self.nodes = FakeNodes(source, events)
        self.docs = FakeDocs(docs, events)
        self.refs = FakeRefs(events)
        self.events = events
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.events.append("commit")
        self.commits += 1

    async def rollback(self) -> None:
        self.events.append("rollback")
        self.rollbacks += 1


def make_case(
    plan: SplitPlan,
    *,
    threshold: int = 2,
) -> tuple[Split, FakeUow, FakeSplitter, Node, list[Document], list[str]]:
    events: list[str] = []
    source = node(1)
    docs = [doc(10, source), doc(11, source), doc(12, source)]
    uow = FakeUow(source, docs, events)
    splitter = FakeSplitter(plan, events)
    case = Split(uow=uow, splitter=splitter, fullness=FakeFullness(threshold))
    return case, uow, splitter, source, docs, events


@pytest.mark.asyncio
async def test_split_requires_unit_of_work() -> None:
    # Arrange
    case = Split(splitter=FakeSplitter(SplitPlan(children=[])), fullness=FakeFullness(1))

    # Act / Assert
    with pytest.raises(MissingUnitOfWork, match="UnitOfWork"):
        await case.run(uid(1))


@pytest.mark.asyncio
async def test_split_requires_splitter() -> None:
    # Arrange
    source = node(1)
    case = Split(uow=FakeUow(source, [], []), fullness=FakeFullness(1))

    # Act / Assert
    with pytest.raises(SplitDependencyError, match="Splitter"):
        await case.run(source.id)


@pytest.mark.asyncio
async def test_split_requires_fullness_policy() -> None:
    # Arrange
    source = node(1)
    case = Split(
        uow=FakeUow(source, [], []),
        splitter=FakeSplitter(SplitPlan(children=[])),
    )

    # Act / Assert
    with pytest.raises(SplitDependencyError, match="FullnessPolicy"):
        await case.run(source.id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("plan", "message"),
    [
        (SplitPlan(children=[]), "at least one child"),
        (
            SplitPlan(children=[child("Empty", [])]),
            "assign documents",
        ),
        (
            SplitPlan(
                children=[
                    child("Known", [uid(10)]),
                    child("Unknown", [uid(11), uid(99)]),
                ]
            ),
            "unknown document",
        ),
        (
            SplitPlan(
                children=[
                    child("First", [uid(10), uid(11)]),
                    child("Duplicate", [uid(11), uid(12)]),
                ]
            ),
            "more than once",
        ),
        (
            SplitPlan(
                children=[
                    child("First", [uid(10)]),
                    child("Second", [uid(11)]),
                ]
            ),
            "unassigned",
        ),
    ],
)
async def test_split_rejects_invalid_plans_before_writes(
    plan: SplitPlan,
    message: str,
) -> None:
    # Arrange
    case, uow, splitter, source, _docs, _events = make_case(plan)

    # Act / Assert
    with pytest.raises(SplitPlanError, match=message):
        await case.run(source.id)

    assert len(splitter.calls) == 1
    assert uow.nodes.added == []
    assert uow.docs.moves == []
    assert uow.refs.cleared == []
    assert source.status == "active"
    assert source.kind == "leaf"
    assert source.doc_count == 3
    assert uow.nodes.saved == [source, source]
    assert uow.nodes.saved_states == [
        ("leaf", "splitting", 3),
        ("leaf", "active", 3),
    ]
    assert uow.commits == 2
    assert uow.rollbacks == 0


@pytest.mark.asyncio
async def test_split_creates_children_moves_documents_and_updates_source() -> None:
    # Arrange
    plan = SplitPlan(
        children=[
            child("Alpha", [uid(10), uid(12)]),
            child("Beta", [uid(11)]),
        ]
    )
    case, uow, splitter, source, docs, events = make_case(plan)

    # Act
    await case.run(source.id)

    # Assert
    assert len(splitter.calls) == 1
    split_source, split_docs = splitter.calls[0]
    assert split_source.id == source.id
    assert split_source.kind == "leaf"
    assert split_source.status == "active"
    assert [item.id for item in split_docs] == [uid(10), uid(11), uid(12)]

    assert len(uow.nodes.added) == 2
    first_child, second_child = uow.nodes.added
    assert first_child.parent_id == source.id
    assert first_child.name == "Alpha"
    assert first_child.kind == "leaf"
    assert first_child.status == "active"
    assert first_child.doc_count == 2
    assert second_child.parent_id == source.id
    assert second_child.name == "Beta"
    assert second_child.doc_count == 1

    assert uow.docs.moves == [
        ([uid(10), uid(12)], first_child.id),
        ([uid(11)], second_child.id),
    ]
    assert {item.id: item.leaf_id for item in docs} == {
        uid(10): first_child.id,
        uid(11): second_child.id,
        uid(12): first_child.id,
    }

    assert source.kind == "branch"
    assert source.status == "active"
    assert source.doc_count == 0
    assert source.version == 2
    assert uow.refs.cleared == [source.id]
    assert uow.nodes.saved == [source, source]
    assert uow.nodes.saved_states == [
        ("leaf", "splitting", 3),
        ("branch", "active", 0),
    ]
    assert uow.commits == 2
    assert events == [
        "get_node",
        "leaf_docs",
        "save_node",
        "commit",
        "split",
        "get_node",
        "leaf_docs",
        "add_node",
        "move_docs",
        "add_node",
        "move_docs",
        "clear_refs",
        "save_node",
        "commit",
    ]
