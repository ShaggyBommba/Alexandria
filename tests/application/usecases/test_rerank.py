from __future__ import annotations

from application.ports import DocHit
from application.usecases.rerank import Rerank
from domain.entity import Document, Node


def make_hit(name: str, score: float) -> DocHit:
    leaf = Node(
        name=f"{name} leaf",
        description=f"{name} leaf description",
        embedding=[0.1, 0.2, 0.3],
    )
    doc = Document(
        leaf=leaf,
        name=name,
        summary=f"{name} summary",
        body=f"{name} body",
        embedding=[0.4, 0.5, 0.6],
    )
    return DocHit(doc=doc, score=score)


async def test_rerank_without_ranker_returns_top_hits_by_score() -> None:
    # Arrange
    low = make_hit("low", 0.2)
    high = make_hit("high", 0.9)
    middle = make_hit("middle", 0.5)
    hits = [low, high, middle]

    # Act
    result = await Rerank().run("query", hits, limit=2)

    # Assert
    assert result == [high, middle]
    assert hits == [low, high, middle]


async def test_rerank_without_ranker_preserves_input_order_for_score_ties() -> None:
    # Arrange
    first = make_hit("first", 0.7)
    second = make_hit("second", 0.7)
    third = make_hit("third", 0.4)
    hits = [first, third, second]

    # Act
    result = await Rerank().run("query", hits, limit=3)

    # Assert
    assert result == [first, second, third]


async def test_rerank_returns_empty_when_limit_is_not_positive() -> None:
    # Arrange
    hits = [make_hit("first", 0.7)]
    original = list(hits)

    # Act
    zero_result = await Rerank().run("query", hits, limit=0)
    negative_result = await Rerank().run("query", hits, limit=-1)

    # Assert
    assert zero_result == []
    assert negative_result == []
    assert hits == original


async def test_rerank_with_ranker_delegates_and_returns_ranker_result() -> None:
    class FakeRanker:
        def __init__(self, result: list[DocHit]) -> None:
            self.result = result
            self.calls: list[tuple[str, list[DocHit], int]] = []

        async def rank(
            self, query: str, hits: list[DocHit], limit: int
        ) -> list[DocHit]:
            self.calls.append((query, hits, limit))
            return self.result

    # Arrange
    first = make_hit("first", 0.1)
    second = make_hit("second", 0.9)
    hits = [first, second]
    ranked = [second]
    ranker = FakeRanker(ranked)

    # Act
    result = await Rerank(ranker=ranker).run("query", hits, limit=1)

    # Assert
    assert result is ranked
    assert ranker.calls == [("query", hits, 1)]
    assert hits == [first, second]
