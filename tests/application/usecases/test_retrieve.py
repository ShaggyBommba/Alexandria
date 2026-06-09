from __future__ import annotations

from uuid import UUID

import pytest

from application.exceptions import RetrieveDependencyError
from application.ports import DocHit, NodeHit, RefHit
from application.usecases.retrieve import Retrieve
from domain.entity import Document, Node, Reference


def uid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012x}")


def vector(*values: float) -> list[float]:
    return list(values)


def node(value: int) -> Node:
    return Node(
        id=uid(value),
        name=f"Node {value}",
        description=f"Description {value}",
        embedding=vector(float(value), 0.0),
    )


def hit(value: int, score: float) -> DocHit:
    leaf = node(value)
    doc = Document(
        id=uid(value + 100),
        leaf_id=leaf.id,
        name=f"Doc {value}",
        summary=f"Summary {value}",
        body=f"Body {value}",
        embedding=vector(float(value), 1.0),
    )
    return DocHit(doc=doc, score=score)


class FakeEmbedder:
    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return self.embedding


class FakeRoute:
    def __init__(self, hits: list[NodeHit]) -> None:
        self.hits = hits
        self.calls: list[tuple[list[float], int]] = []

    async def run(self, embedding: list[float], limit: int = 10) -> list[NodeHit]:
        self.calls.append((embedding, limit))
        return self.hits


class FakeRefs:
    def __init__(self, hits: list[RefHit]) -> None:
        self.hits = hits
        self.calls: list[tuple[set[UUID], list[float], int]] = []

    async def near(
        self,
        ids: set[UUID],
        embedding: list[float],
        limit: int,
    ) -> list[RefHit]:
        self.calls.append((set(ids), embedding, limit))
        return self.hits


class FakeSearch:
    def __init__(self, hits: list[DocHit]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, list[float], set[UUID], int]] = []

    async def find(
        self,
        query: str,
        embedding: list[float],
        leaves: set[UUID],
        limit: int,
    ) -> list[DocHit]:
        self.calls.append((query, embedding, set(leaves), limit))
        return self.hits


class FakeRerank:
    def __init__(self, result: list[DocHit]) -> None:
        self.result = result
        self.calls: list[tuple[str, list[DocHit], int]] = []

    async def run(self, query: str, hits: list[DocHit], limit: int) -> list[DocHit]:
        self.calls.append((query, hits, limit))
        return self.result


async def test_retrieve_raises_application_error_when_required_dependencies_missing() -> None:
    # Arrange
    retrieve = Retrieve()

    # Act / Assert
    with pytest.raises(RetrieveDependencyError, match="Embedder, Route, Search") as error:
        await retrieve.run("query")

    assert error.value.code == "app.retrieve.dependency"


async def test_retrieve_returns_empty_for_non_positive_limit_without_calling_dependencies() -> None:
    # Arrange
    embedding = vector(0.1, 0.2)
    embedder = FakeEmbedder(embedding)
    route = FakeRoute([NodeHit(node(1), 0.0)])
    search = FakeSearch([hit(1, 0.9)])
    refs = FakeRefs([])
    rerank = FakeRerank([hit(2, 1.0)])
    retrieve = Retrieve(
        search=search,
        refs=refs,
        embedder=embedder,
        route=route,
        rerank=rerank,
    )

    # Act
    zero = await retrieve.run("query", limit=0)
    negative = await retrieve.run("query", limit=-1)

    # Assert
    assert zero == []
    assert negative == []
    assert embedder.calls == []
    assert route.calls == []
    assert refs.calls == []
    assert search.calls == []
    assert rerank.calls == []


async def test_retrieve_embeds_routes_and_searches_scoped_leaf_set() -> None:
    # Arrange
    embedding = vector(0.7, 0.8)
    first_leaf = node(1)
    second_leaf = node(2)
    embedder = FakeEmbedder(embedding)
    route = FakeRoute(
        [
            NodeHit(first_leaf, 0.1),
            NodeHit(second_leaf, 0.2),
        ],
    )
    first = hit(1, 0.1)
    second = hit(2, 0.9)
    extra = hit(3, 0.8)
    search = FakeSearch([first, second, extra])
    retrieve = Retrieve(search=search, embedder=embedder, route=route)

    # Act
    result = await retrieve.run("query text", limit=2)

    # Assert
    assert result == [first, second]
    assert embedder.calls == ["query text"]
    assert route.calls == [(embedding, 2)]
    assert search.calls == [
        ("query text", embedding, {first_leaf.id, second_leaf.id}, 2),
    ]


async def test_retrieve_expands_scope_with_references_before_searching() -> None:
    # Arrange
    embedding = vector(0.3, 0.4)
    routed_leaf = node(1)
    referenced_leaf = node(2)
    reference = Reference(
        from_node_id=routed_leaf.id,
        to_node_id=referenced_leaf.id,
        distance=0.12,
        rank=0,
    )
    embedder = FakeEmbedder(embedding)
    route = FakeRoute([NodeHit(routed_leaf, 0.05)])
    refs = FakeRefs([RefHit(ref=reference, node=referenced_leaf, distance=0.12)])
    search = FakeSearch([])
    retrieve = Retrieve(search=search, refs=refs, embedder=embedder, route=route)

    # Act
    result = await retrieve.run("query text", limit=3)

    # Assert
    assert result == []
    assert refs.calls == [({routed_leaf.id}, embedding, 3)]
    assert search.calls == [
        ("query text", embedding, {routed_leaf.id, referenced_leaf.id}, 3),
    ]


async def test_retrieve_calls_rerank_when_configured() -> None:
    # Arrange
    embedding = vector(0.5, 0.6)
    leaf = node(1)
    search_hit = hit(1, 0.1)
    ranked_hit = hit(2, 1.0)
    embedder = FakeEmbedder(embedding)
    route = FakeRoute([NodeHit(leaf, 0.0)])
    search = FakeSearch([search_hit])
    rerank = FakeRerank([ranked_hit])
    retrieve = Retrieve(
        search=search,
        embedder=embedder,
        route=route,
        rerank=rerank,
    )

    # Act
    result = await retrieve.run("query text", limit=1)

    # Assert
    assert result == [ranked_hit]
    assert search.calls == [("query text", embedding, {leaf.id}, 1)]
    assert rerank.calls == [("query text", [search_hit], 1)]
