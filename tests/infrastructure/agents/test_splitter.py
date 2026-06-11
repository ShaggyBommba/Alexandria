from __future__ import annotations

from uuid import UUID

import pytest

from application.ports import Splitter
from domain.entity import Document, Node
from infrastructure.agents.splitter import LangSplitter, make_splitter
from infrastructure.config import SplitterProvider, SplitterSettings
from infrastructure.exceptions import SplitterResponseError


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


def node() -> Node:
    return Node(
        id=uid(1),
        name="Source",
        description="Source leaf",
        embedding=[1.0, 0.0],
    )


def doc(value: int, source: Node) -> Document:
    return Document(
        id=uid(value),
        leaf_id=source.id,
        source_key=f"source:{value}",
        name=f"Doc {value}",
        summary=f"Summary {value}",
        body=f"Body {value}",
        embedding=[1.0, 0.0],
    )


def adapter(agent: FakeAgent) -> LangSplitter:
    splitter = LangSplitter(client=object())  # type: ignore[arg-type]
    splitter.agent = agent  # type: ignore[method-assign]
    return splitter


def test_lang_splitter_satisfies_port() -> None:
    splitter = LangSplitter(client=object())  # type: ignore[arg-type]

    assert isinstance(splitter, Splitter)


@pytest.mark.asyncio
async def test_splitter_validates_structured_output_and_returns_split_plan() -> None:
    source = node()
    first = doc(10, source)
    second = doc(11, source)
    agent = FakeAgent(
        {
            "structured_response": {
                "children": [
                    {
                        "name": "  Alpha child  ",
                        "description": "  Alpha documents  ",
                        "embedding": [0.1, 0.2],
                        "docs": [str(first.id)],
                    },
                    {
                        "name": "Beta child",
                        "description": "Beta documents",
                        "embedding": [0.3, 0.4],
                        "docs": [str(second.id)],
                    },
                ]
            }
        }
    )
    splitter = adapter(agent)

    plan = await splitter.split(source, [second, first])

    assert [child.name for child in plan.children] == ["Alpha child", "Beta child"]
    assert [child.description for child in plan.children] == [
        "Alpha documents",
        "Beta documents",
    ]
    assert plan.children[0].embedding == [0.1, 0.2]
    assert plan.children[0].docs == [first.id]
    messages = agent.payload["messages"]
    assert "semantic wiki" in messages[0].content
    assert str(first.id) in messages[1].content
    assert str(second.id) in messages[1].content


@pytest.mark.asyncio
async def test_splitter_rejects_missing_structured_response() -> None:
    splitter = adapter(FakeAgent({"messages": []}))

    with pytest.raises(SplitterResponseError, match="no structured response"):
        await splitter.split(node(), [])


@pytest.mark.asyncio
async def test_splitter_rejects_invalid_structured_output() -> None:
    splitter = adapter(
        FakeAgent(
            {
                "structured_response": {
                    "children": [
                        {
                            "name": "  ",
                            "description": "Missing useful name",
                            "embedding": [],
                            "docs": [],
                        }
                    ]
                }
            }
        )
    )

    with pytest.raises(SplitterResponseError, match="invalid structured response"):
        await splitter.split(node(), [])


def test_splitter_factory_returns_none_when_disabled() -> None:
    settings = SplitterSettings()

    assert make_splitter(SplitterProvider.NONE, settings) is None


@pytest.mark.parametrize("value", [None, "", "   "])
def test_splitter_factory_defers_missing_or_blank_api_key(
    value: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SplitterSettings(provider=SplitterProvider.OPENAI, api_key=value)
    captured: dict[str, object] = {}

    class FakeOpenAIClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("infrastructure.agents.splitter.ChatOpenAI", FakeOpenAIClient)

    splitter = make_splitter(SplitterProvider.OPENAI, settings)

    assert isinstance(splitter, LangSplitter)
    assert hasattr(captured["api_key"], "get_secret_value")


def test_splitter_factory_constructs_lang_splitter_for_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SplitterSettings(provider=SplitterProvider.OPENAI, api_key="test-key")
    captured: dict[str, object] = {}

    class FakeOpenAIClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("infrastructure.agents.splitter.ChatOpenAI", FakeOpenAIClient)

    splitter = make_splitter(SplitterProvider.OPENAI, settings)

    assert isinstance(splitter, LangSplitter)
    assert captured["api_key"].get_secret_value() == "test-key"
    assert captured["model"] == "gpt-4o-mini"
