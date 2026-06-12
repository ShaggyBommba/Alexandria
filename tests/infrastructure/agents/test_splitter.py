from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import SecretStr

from application.ports import Splitter
from domain.entity import Document, Node
from infrastructure.agents.splitter import LangSplitter, make_splitter
from infrastructure.config import SplitterProvider, SplitterSettings
from infrastructure.exceptions import SplitterConfigError, SplitterResponseError


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


class FakeEmbedder:
    def __init__(self, embeddings: dict[str, list[float]] | None = None) -> None:
        self.embeddings = embeddings or {}
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return self.embeddings.get(text, [0.0, 0.0])


def adapter(agent: FakeAgent, embedder: FakeEmbedder | None = None) -> LangSplitter:
    splitter = LangSplitter(client=object(), embedder=embedder or FakeEmbedder())  # type: ignore[arg-type]
    splitter.agent = agent  # type: ignore[method-assign]
    return splitter


def test_lang_splitter_satisfies_port() -> None:
    splitter = LangSplitter(client=object(), embedder=FakeEmbedder())  # type: ignore[arg-type]

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
                        "docs": [str(first.id)],
                    },
                    {
                        "name": "Beta child",
                        "description": "Beta documents",
                        "docs": [str(second.id)],
                    },
                ]
            }
        }
    )
    embedder = FakeEmbedder(
        {"Alpha documents": [0.1, 0.2], "Beta documents": [0.3, 0.4]}
    )
    splitter = adapter(agent, embedder)

    plan = await splitter.split(source, [second, first])

    assert [child.name for child in plan.children] == ["Alpha child", "Beta child"]
    assert [child.description for child in plan.children] == [
        "Alpha documents",
        "Beta documents",
    ]
    assert plan.children[0].embedding == [0.1, 0.2]
    assert plan.children[1].embedding == [0.3, 0.4]
    assert plan.children[0].docs == [first.id]
    assert embedder.calls == ["Alpha documents", "Beta documents"]
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

    assert make_splitter(SplitterProvider.NONE, settings, FakeEmbedder()) is None


@pytest.mark.parametrize("value", [None, SecretStr(""), SecretStr("   ")])
def test_splitter_factory_rejects_missing_or_blank_api_key(
    value: SecretStr | None,
) -> None:
    settings = SplitterSettings(provider=SplitterProvider.OPENAI, api_key=value)

    with pytest.raises(SplitterConfigError, match="requires an api_key"):
        make_splitter(SplitterProvider.OPENAI, settings, FakeEmbedder())


def test_splitter_factory_constructs_lang_splitter_for_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SplitterSettings(provider=SplitterProvider.OPENAI, api_key=SecretStr("test-key"))
    captured: dict[str, object] = {}

    class FakeOpenAIClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("infrastructure.agents.splitter.ChatOpenAI", FakeOpenAIClient)

    embedder = FakeEmbedder()
    splitter = make_splitter(SplitterProvider.OPENAI, settings, embedder)

    assert isinstance(splitter, LangSplitter)
    assert splitter.embedder is embedder
    assert isinstance(captured["api_key"], SecretStr)
    assert captured["api_key"].get_secret_value() == "test-key"
    assert captured["model"] == "gpt-4o-mini"
