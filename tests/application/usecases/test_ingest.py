from __future__ import annotations

from uuid import UUID

import pytest

from application.exceptions import (
    IngestDependencyError,
    IngestLeafError,
    MissingUnitOfWork,
)
from application.ports import DocIn, NodeHit
from application.usecases.ingest import Ingest
from domain.entity import Document, Job, Node
from domain.values import JobKind


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


def stored_doc(value: int, leaf: Node) -> Document:
    return Document(
        id=uid(value),
        leaf_id=leaf.id,
        source_key=f"source:{value}",
        name=f"Doc {value}",
        summary=f"Summary {value}",
        body=f"Body {value}",
        embedding=[float(value), 0.0],
    )


class FakeEmbedder:
    def __init__(self, embedding: list[float], events: list[str]) -> None:
        self.embedding = embedding
        self.events = events
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.events.append("embed")
        self.calls.append(text)
        return self.embedding


class FakeSummarizer:
    def __init__(self, summary: str, events: list[str]) -> None:
        self.summary = summary
        self.events = events
        self.calls: list[DocIn] = []

    async def summarize(self, doc: DocIn) -> str:
        self.events.append("summarize")
        self.calls.append(doc)
        return self.summary


class FakeSeed:
    def __init__(self, root: Node, events: list[str]) -> None:
        self.root = root
        self.events = events
        self.runs = 0

    async def run(self) -> Node:
        self.events.append("seed")
        self.runs += 1
        return self.root


class FakeRoute:
    def __init__(self, hits: list[NodeHit], events: list[str]) -> None:
        self.hits = hits
        self.events = events
        self.calls: list[tuple[list[float], int]] = []

    async def run(self, embedding: list[float], limit: int = 10) -> list[NodeHit]:
        self.events.append("route")
        self.calls.append((embedding, limit))
        return self.hits


class FakeDocs:
    def __init__(self, docs: list[Document], events: list[str]) -> None:
        self.docs = docs
        self.events = events

    async def add(self, doc: Document) -> UUID:
        self.events.append("add_doc")
        self.docs.append(doc)
        return doc.id


class FakeNodes:
    def __init__(self, docs: FakeDocs, events: list[str]) -> None:
        self.docs = docs
        self.events = events
        self.count_calls: list[UUID] = []
        self.saved: list[Node] = []

    async def count(self, id: UUID) -> int:
        self.events.append("count")
        self.count_calls.append(id)
        return sum(1 for doc in self.docs.docs if doc.leaf_id == id)

    async def save(self, node: Node) -> None:
        self.events.append("save_node")
        self.saved.append(node)


class FakeOutbox:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.jobs: list[Job] = []

    async def append(self, job: Job) -> UUID:
        self.events.append("append_job")
        self.jobs.append(job)
        return job.id


class FakeUow:
    def __init__(
        self,
        events: list[str],
        docs: list[Document] | None = None,
    ) -> None:
        self.events = events
        self.docs = FakeDocs(docs or [], events)
        self.nodes = FakeNodes(self.docs, events)
        self.outbox = FakeOutbox(events)
        self.commits = 0

    async def commit(self) -> None:
        self.events.append("commit")
        self.commits += 1


def make_case(
    *,
    events: list[str] | None = None,
    uow: FakeUow | None = None,
    embedder: FakeEmbedder | None = None,
    summarizer: FakeSummarizer | None = None,
    seed: FakeSeed | None = None,
    route: FakeRoute | None = None,
    max_leaf_docs: int | None = None,
    route_limit: int = 10,
) -> Ingest:
    event_log = events if events is not None else []
    root = node(1)
    embedding = [0.5, 0.25]
    return Ingest(
        uow=uow if uow is not None else FakeUow(event_log),
        embedder=embedder
        if embedder is not None
        else FakeEmbedder(embedding, event_log),
        summarizer=(
            summarizer
            if summarizer is not None
            else FakeSummarizer("Concise summary.", event_log)
        ),
        seed=seed if seed is not None else FakeSeed(root, event_log),
        route=route
        if route is not None
        else FakeRoute([NodeHit(root, 0.0)], event_log),
        max_leaf_docs=max_leaf_docs,
        route_limit=route_limit,
    )


@pytest.mark.asyncio
async def test_ingest_requires_unit_of_work() -> None:
    # Arrange
    events: list[str] = []
    case = make_case(events=events, uow=None)
    case.uow = None

    # Act / Assert
    with pytest.raises(MissingUnitOfWork, match="UnitOfWork"):
        await case.run(DocIn(name="Missing", body="dependency"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dependency", "message"),
    [
        ("embedder", "Embedder"),
        ("summarizer", "Summarizer"),
        ("seed", "Seed"),
        ("route", "Route"),
    ],
)
async def test_ingest_requires_all_external_dependencies(
    dependency: str,
    message: str,
) -> None:
    # Arrange
    case = make_case()
    setattr(case, dependency, None)

    # Act / Assert
    with pytest.raises(IngestDependencyError, match=message):
        await case.run(DocIn(name="Missing", body="dependency"))


@pytest.mark.asyncio
async def test_ingest_persists_document_on_nearest_active_leaf() -> None:
    # Arrange
    events: list[str] = []
    root = node(1, kind="branch")
    branch = node(2, kind="branch")
    retired = node(3, status="retired")
    farther = node(4)
    chosen = node(5)
    embedding = [0.8, 0.2]
    uow = FakeUow(events)
    embedder = FakeEmbedder(embedding, events)
    summarizer = FakeSummarizer("Routes through the semantic index.", events)
    seed = FakeSeed(root, events)
    route = FakeRoute(
        [
            NodeHit(branch, 0.01),
            NodeHit(retired, 0.02),
            NodeHit(farther, 0.4),
            NodeHit(chosen, 0.2),
        ],
        events,
    )
    doc = DocIn(name="Routing Notes", body="Use beam search.", source_key="wiki:1")
    case = Ingest(
        uow=uow,
        embedder=embedder,
        summarizer=summarizer,
        seed=seed,
        route=route,
        route_limit=4,
    )

    # Act
    doc_id = await case.run(doc)

    # Assert
    saved = uow.docs.docs[0]
    assert doc_id == saved.id
    assert saved.name == "Routing Notes"
    assert saved.body == "Use beam search."
    assert saved.source_key == "wiki:1"
    assert saved.summary == "Routes through the semantic index."
    assert saved.leaf_id == chosen.id
    assert saved.embedding is embedding
    assert chosen.doc_count == 1
    assert uow.nodes.count_calls == [chosen.id]
    assert uow.nodes.saved == [chosen]
    assert uow.outbox.jobs == []
    assert uow.commits == 1
    assert summarizer.calls == [doc]
    assert embedder.calls == ["Routing Notes\n\nUse beam search."]
    assert seed.runs == 1
    assert route.calls == [(embedding, 4)]
    assert events == [
        "summarize",
        "embed",
        "seed",
        "route",
        "add_doc",
        "count",
        "save_node",
        "commit",
    ]


@pytest.mark.asyncio
async def test_ingest_fails_explicitly_when_route_returns_no_active_leaf() -> None:
    # Arrange
    events: list[str] = []
    root = node(1, kind="branch")
    uow = FakeUow(events)
    case = Ingest(
        uow=uow,
        embedder=FakeEmbedder([0.1, 0.2], events),
        summarizer=FakeSummarizer("Summary.", events),
        seed=FakeSeed(root, events),
        route=FakeRoute(
            [
                NodeHit(node(2, kind="branch"), 0.1),
                NodeHit(node(3, status="retired"), 0.2),
            ],
            events,
        ),
    )

    # Act / Assert
    with pytest.raises(IngestLeafError, match="active leaf"):
        await case.run(DocIn(name="No Leaf", body="Cannot attach."))

    assert uow.docs.docs == []
    assert uow.nodes.saved == []
    assert uow.outbox.jobs == []
    assert uow.commits == 0
    assert events == ["summarize", "embed", "seed", "route"]


@pytest.mark.asyncio
async def test_ingest_appends_split_check_when_explicit_policy_says_leaf_is_full() -> (
    None
):
    # Arrange
    events: list[str] = []
    leaf = node(1)
    existing = stored_doc(10, leaf)
    uow = FakeUow(events, docs=[existing])
    case = Ingest(
        uow=uow,
        embedder=FakeEmbedder([0.3, 0.7], events),
        summarizer=FakeSummarizer("Summary.", events),
        seed=FakeSeed(leaf, events),
        route=FakeRoute([NodeHit(leaf, 0.0)], events),
        max_leaf_docs=2,
    )

    # Act
    await case.run(DocIn(name="Full Leaf", body="This tips the count."))

    # Assert
    assert leaf.doc_count == 2
    assert len(uow.outbox.jobs) == 1
    job = uow.outbox.jobs[0]
    assert job.kind == JobKind.SPLIT_CHECK
    assert job.payload == {"node_id": str(leaf.id)}
    assert job.key == leaf.id
    assert uow.commits == 1
    assert events == [
        "summarize",
        "embed",
        "seed",
        "route",
        "add_doc",
        "count",
        "save_node",
        "append_job",
        "commit",
    ]


@pytest.mark.asyncio
async def test_ingest_does_not_append_split_check_before_policy_is_full() -> None:
    # Arrange
    events: list[str] = []
    leaf = node(1)
    uow = FakeUow(events)
    case = Ingest(
        uow=uow,
        embedder=FakeEmbedder([0.3, 0.7], events),
        summarizer=FakeSummarizer("Summary.", events),
        seed=FakeSeed(leaf, events),
        route=FakeRoute([NodeHit(leaf, 0.0)], events),
        max_leaf_docs=2,
    )

    # Act
    await case.run(DocIn(name="Not Full", body="One document only."))

    # Assert
    assert leaf.doc_count == 1
    assert uow.outbox.jobs == []
    assert uow.commits == 1
