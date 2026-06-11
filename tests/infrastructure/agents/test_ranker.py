from __future__ import annotations

from uuid import UUID

import pytest

from application.ports import DocHit, Ranker
from domain.entity import Document, Node
from infrastructure.agents.ranker import LangRanker, make_ranker
from infrastructure.config import RankerProvider, RankerSettings
from infrastructure.exceptions import RankerConfigError, RankerResponseError


class FakeAgent:
    def __init__(self, output=None, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.payload = None

    async def ainvoke(self, payload):
        self.payload = payload
        if self.error:
            raise self.error
        return self.output


def uid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012x}")


def hit(value: int, score: float = 0.5) -> DocHit:
    leaf = Node(
        id=uid(value),
        name=f"Leaf {value}",
        description=f"Leaf {value}",
        embedding=[1.0, 0.0],
    )
    doc = Document(
        id=uid(value + 100),
        leaf_id=leaf.id,
        source_key=f"source:{value}",
        name=f"Doc {value}",
        summary=f"Summary {value}",
        body=f"Body {value}",
        embedding=[1.0, 0.0],
    )
    return DocHit(doc=doc, score=score, distance=0.1, bm25=0.2)


def adapter(agent: FakeAgent) -> LangRanker:
    ranker = LangRanker(client=object())  # type: ignore[arg-type]
    ranker.agent = agent  # type: ignore[method-assign]
    return ranker


def test_lang_ranker_satisfies_port() -> None:
    ranker = LangRanker(client=object())  # type: ignore[arg-type]

    assert isinstance(ranker, Ranker)


@pytest.mark.asyncio
async def test_ranker_returns_existing_hits_in_provider_order() -> None:
    first = hit(1, 0.1)
    second = hit(2, 0.9)
    agent = FakeAgent(
        {
            "structured_response": {
                "documents": [
                    {"id": str(second.doc.id), "rationale": "best match"},
                    {"id": str(first.doc.id), "rationale": "secondary"},
                ]
            }
        }
    )
    ranker = adapter(agent)

    result = await ranker.rank("query text", [first, second], limit=2)

    assert result == [second, first]
    messages = agent.payload["messages"]
    assert "semantic wiki" in messages[0].content
    assert "query text" in messages[1].content
    assert str(first.doc.id) in messages[1].content
    assert str(second.doc.id) in messages[1].content


@pytest.mark.asyncio
async def test_ranker_rejects_unknown_document_ids() -> None:
    first = hit(1)
    agent = FakeAgent(
        {
            "structured_response": {
                "documents": [{"id": str(uid(999)), "rationale": "invented"}]
            }
        }
    )
    ranker = adapter(agent)

    with pytest.raises(RankerResponseError, match="unknown document"):
        await ranker.rank("query text", [first], limit=1)


@pytest.mark.asyncio
async def test_ranker_rejects_duplicate_document_ids() -> None:
    first = hit(1)
    agent = FakeAgent(
        {
            "structured_response": {
                "documents": [
                    {"id": str(first.doc.id), "rationale": "first"},
                    {"id": str(first.doc.id), "rationale": "duplicate"},
                ]
            }
        }
    )
    ranker = adapter(agent)

    with pytest.raises(RankerResponseError, match="duplicate document"):
        await ranker.rank("query text", [first], limit=2)


@pytest.mark.asyncio
async def test_ranker_validates_full_provider_response_before_limiting() -> None:
    first = hit(1)
    second = hit(2)
    agent = FakeAgent(
        {
            "structured_response": {
                "documents": [
                    {"id": str(first.doc.id), "rationale": "first"},
                    {"id": str(second.doc.id), "rationale": "second"},
                    {"id": str(first.doc.id), "rationale": "duplicate"},
                ]
            }
        }
    )
    ranker = adapter(agent)

    with pytest.raises(RankerResponseError, match="duplicate document"):
        await ranker.rank("query text", [first, second], limit=1)


@pytest.mark.asyncio
async def test_ranker_rejects_missing_structured_response() -> None:
    ranker = adapter(FakeAgent({"messages": []}))

    with pytest.raises(RankerResponseError, match="no structured response"):
        await ranker.rank("query text", [hit(1)], limit=1)


@pytest.mark.asyncio
async def test_ranker_returns_empty_without_provider_call_when_limit_or_hits_empty() -> None:
    agent = FakeAgent(
        {
            "structured_response": {
                "documents": [{"id": str(uid(101)), "rationale": "unused"}]
            }
        }
    )
    ranker = adapter(agent)

    assert await ranker.rank("query text", [hit(1)], limit=0) == []
    assert await ranker.rank("query text", [], limit=1) == []
    assert agent.payload is None


def test_ranker_factory_returns_none_when_disabled() -> None:
    settings = RankerSettings()

    assert make_ranker(RankerProvider.NONE, settings) is None


@pytest.mark.parametrize("value", [None, "", "   "])
def test_ranker_factory_rejects_missing_or_blank_api_key(value: str | None) -> None:
    settings = RankerSettings(provider=RankerProvider.OPENAI, api_key=value)

    with pytest.raises(RankerConfigError, match="requires an api_key"):
        make_ranker(RankerProvider.OPENAI, settings)


def test_ranker_factory_constructs_lang_ranker_for_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = RankerSettings(provider=RankerProvider.OPENAI, api_key="test-key")
    captured: dict[str, object] = {}

    class FakeOpenAIClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("infrastructure.agents.ranker.ChatOpenAI", FakeOpenAIClient)

    ranker = make_ranker(RankerProvider.OPENAI, settings)

    assert isinstance(ranker, LangRanker)
    assert captured["api_key"] == "test-key"
    assert captured["model"] == "gpt-4o-mini"
