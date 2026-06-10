from __future__ import annotations

import pytest

from application.ports import DocIn, Summarizer
from infrastructure.agents.summarizer import LangSummarizer, make_summarizer
from infrastructure.config import SummarizerProvider, SummarizerSettings
from infrastructure.exceptions import AgentError, SummarizerConfigError


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


def adapter(agent: FakeAgent) -> LangSummarizer:
    summarizer = LangSummarizer(client=object())  # type: ignore[arg-type]
    summarizer.agent = agent  # type: ignore[method-assign]
    return summarizer


def test_lang_summarizer_satisfies_port() -> None:
    summarizer = LangSummarizer(client=object())  # type: ignore[arg-type]

    assert isinstance(summarizer, Summarizer)


@pytest.mark.asyncio
async def test_summarize_sends_document_prompt_and_returns_summary() -> None:
    agent = FakeAgent(
        {"structured_response": {"summary": "  Uses beam search for routing.  "}}
    )
    summarizer = adapter(agent)
    doc = DocIn(
        name="Routing memo",
        source_key="memo:1",
        body="Beam search keeps multiple candidate paths while routing documents.",
    )

    summary = await summarizer.summarize(doc)

    assert summary == "Uses beam search for routing."
    messages = agent.payload["messages"]
    assert "semantic wiki" in messages[0].content
    assert "Routing memo" in messages[1].content
    assert "memo:1" in messages[1].content
    assert "Beam search keeps multiple candidate paths" in messages[1].content


@pytest.mark.asyncio
async def test_summarize_wraps_agent_execution_errors() -> None:
    summarizer = adapter(FakeAgent(error=ValueError("provider failed")))
    doc = DocIn(name="Broken", body="Body")

    with pytest.raises(AgentError, match="Summarizer agent execution failed"):
        await summarizer.summarize(doc)


@pytest.mark.asyncio
async def test_summarize_rejects_missing_structured_response() -> None:
    summarizer = adapter(FakeAgent({"messages": []}))
    doc = DocIn(name="Missing", body="Body")

    with pytest.raises(AgentError, match="no structured response"):
        await summarizer.summarize(doc)


@pytest.mark.asyncio
async def test_summarize_rejects_empty_summary() -> None:
    summarizer = adapter(FakeAgent({"structured_response": {"summary": "   "}}))
    doc = DocIn(name="Empty", body="Body")

    with pytest.raises(AgentError, match="empty summary"):
        await summarizer.summarize(doc)


@pytest.mark.parametrize(
    "value",
    [None, "", "   "],
)
def test_factory_rejects_missing_or_blank_api_key(value: str | None) -> None:
    settings = SummarizerSettings(api_key=value)

    with pytest.raises(SummarizerConfigError, match="requires an api_key"):
        make_summarizer(SummarizerProvider.OPENAI, settings)


def test_factory_constructs_lang_summarizer_for_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SummarizerSettings(api_key="test-key")
    captured: dict[str, object] = {}

    class FakeOpenAIClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "infrastructure.agents.summarizer.ChatOpenAI",
        FakeOpenAIClient,
    )

    summarizer = make_summarizer(SummarizerProvider.OPENAI, settings)

    assert isinstance(summarizer, LangSummarizer)
    assert captured["api_key"] == "test-key"
    assert captured["model"] == "gpt-4o-mini"
