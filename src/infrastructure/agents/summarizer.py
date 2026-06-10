from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from functools import cached_property
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError

from application.ports import DocIn
from application.ports import Summarizer as SummarizerPort
from infrastructure.config import SummarizerProvider, SummarizerSettings
from infrastructure.exceptions import AgentError, SummarizerConfigError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a summarization agent for Alexandria, a semantic wiki. Create "
    "concise, factual document summaries for indexing and retrieval. Use only "
    "facts supported by the supplied document."
)

USER_PROMPT = (
    "Summarize the document below. Focus on the central topic, important "
    "entities, durable facts, and any outcome or decision that would help a "
    "reader find this document later. Return only the structured summary."
)


class SummaryResult(BaseModel):
    """Structured summary returned by the LangChain agent."""

    summary: str = Field(
        description="Concise factual summary of the supplied document.",
    )


class LangSummarizer:
    """LangChain adapter that summarizes documents for indexing."""

    def __init__(
        self,
        client: BaseChatModel,
        tools: Sequence[Any] | None = None,
    ) -> None:
        self.client = client
        self.tools = list(tools or [])

    @cached_property
    def agent(self) -> Runnable:
        """Create the LangChain agent graph."""
        return create_agent(
            model=self.client,
            tools=self.tools,
            response_format=SummaryResult,
        )

    async def summarize(self, doc: DocIn) -> str:
        """Summarize one document through the LangChain agent."""
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                (
                    "human",
                    USER_PROMPT
                    + "\n\nName:\n{name}\n\nSource key:\n{source_key}\n\nBody:\n{body}",
                ),
            ]
        )
        messages = prompt.format_messages(
            name=doc.name,
            source_key=doc.source_key or "",
            body=doc.body,
        )

        try:
            output = await self.agent.ainvoke({"messages": messages})
            result = self.parsed(output)
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError(f"Summarizer agent execution failed: {exc}") from exc

        summary = result.summary.strip()
        if not summary:
            raise AgentError("Summarizer agent returned an empty summary")

        logger.debug(
            "Agent returned summary result: %s", result.model_dump_json(indent=2)
        )
        return summary

    @staticmethod
    def parsed(output: Any) -> SummaryResult:
        """Validate the structured response returned by the agent graph."""
        if isinstance(output, SummaryResult):
            return output

        if not isinstance(output, Mapping):
            raise AgentError("Summarizer agent returned an invalid response")

        if "structured_response" not in output:
            raise AgentError("Summarizer agent returned no structured response")

        structured = output["structured_response"]
        try:
            return SummaryResult.model_validate(structured)
        except ValidationError as exc:
            raise AgentError(
                f"Summarizer agent returned invalid structured response: {exc}"
            ) from exc


class LazySummarizer:
    """Defer summarizer construction until it is first used."""

    def __init__(self, factory: Callable[[], SummarizerPort]) -> None:
        self._factory = factory
        self._instance: SummarizerPort | None = None

    async def summarize(self, doc: DocIn) -> str:
        if self._instance is None:
            self._instance = self._factory()
        return await self._instance.summarize(doc)


def make_summarizer(
    provider: SummarizerProvider,
    settings: SummarizerSettings,
) -> SummarizerPort:
    """Build the configured summarizer adapter."""
    if provider is SummarizerProvider.OPENAI:
        api_key = (settings.api_key or "").strip()
        if not api_key:
            raise SummarizerConfigError(
                "summarizer provider openai requires an api_key"
            )
        return LangSummarizer(
            client=ChatOpenAI(
                api_key=api_key,
                base_url=settings.base_url,
                model=settings.model,
                timeout=settings.timeout_seconds,
            ),
        )

    raise SummarizerConfigError(f"unsupported summarizer provider: {provider}")
