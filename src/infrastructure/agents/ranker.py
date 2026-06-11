from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from functools import cached_property
from typing import Any
from uuid import UUID

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError

from application.ports import DocHit
from application.ports import Ranker as RankerPort
from infrastructure.config import RankerProvider, RankerSettings
from infrastructure.exceptions import RankerConfigError, RankerError, RankerResponseError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a ranking agent for Alexandria, a semantic wiki. Rerank only the "
    "candidate document ids supplied by the application for the user's query."
)

USER_PROMPT = (
    "Return only the structured ranked document ids. Do not invent ids and do "
    "not include the same id more than once."
)


class RankedDocument(BaseModel):
    """One provider-ranked document id with optional diagnostic rationale."""

    id: UUID
    rationale: str | None = None


class RankResult(BaseModel):
    """Structured rank result returned by the LangChain agent."""

    documents: list[RankedDocument] = Field(min_length=1)


class LangRanker:
    """LangChain adapter that reranks already-scoped document hits."""

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
            response_format=RankResult,
        )

    async def rank(self, query: str, hits: list[DocHit], limit: int) -> list[DocHit]:
        """Rerank known hits and reject unknown or duplicate provider ids."""
        if limit <= 0 or not hits:
            return []

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                (
                    "human",
                    USER_PROMPT
                    + "\n\nQuery:\n{query}\n\nCandidates:\n{candidates}",
                ),
            ]
        )
        messages = prompt.format_messages(
            query=query,
            candidates=candidate_context(hits),
        )

        try:
            output = await self.agent.ainvoke({"messages": messages})
            result = self.parsed(output)
        except RankerResponseError:
            raise
        except Exception as exc:
            raise RankerError(f"Ranker agent execution failed: {exc}") from exc

        by_id = {hit.doc.id: hit for hit in hits}
        seen: set[UUID] = set()
        ranked: list[DocHit] = []
        for item in result.documents:
            if item.id not in by_id:
                raise RankerResponseError(
                    f"Ranker agent returned unknown document {item.id}"
                )
            if item.id in seen:
                raise RankerResponseError(
                    f"Ranker agent returned duplicate document {item.id}"
                )

            seen.add(item.id)
            ranked.append(by_id[item.id])

        logger.debug(
            "Agent returned rank result: %s", result.model_dump_json(indent=2)
        )
        return ranked[:limit]

    @staticmethod
    def parsed(output: Any) -> RankResult:
        """Validate the structured response returned by the agent graph."""
        if isinstance(output, RankResult):
            return output

        if not isinstance(output, Mapping):
            raise RankerResponseError("Ranker agent returned an invalid response")

        if "structured_response" not in output:
            raise RankerResponseError("Ranker agent returned no structured response")

        structured = output["structured_response"]
        try:
            return RankResult.model_validate(structured)
        except ValidationError as exc:
            raise RankerResponseError(
                f"Ranker agent returned invalid structured response: {exc}"
            ) from exc


def candidate_context(hits: list[DocHit]) -> str:
    """Return deterministic candidate context for the ranker prompt."""
    lines: list[str] = []
    for hit in hits:
        doc = hit.doc
        lines.append(
            "\n".join(
                [
                    f"Document id: {doc.id}",
                    f"Name: {doc.name}",
                    f"Summary: {doc.summary}",
                    f"Body: {doc.body}",
                    f"Score: {hit.score}",
                    f"Distance: {hit.distance}",
                    f"BM25: {hit.bm25}",
                ]
            )
        )
    return "\n\n---\n\n".join(lines)


def make_ranker(
    provider: RankerProvider,
    settings: RankerSettings,
) -> RankerPort | None:
    """Build the configured ranker adapter, or disable it explicitly."""
    if provider is RankerProvider.NONE:
        return None

    if provider is RankerProvider.OPENAI:
        api_key = (settings.api_key or "").strip()
        if not api_key:
            raise RankerConfigError("ranker provider openai requires an api_key")
        return LangRanker(
            client=ChatOpenAI(
                api_key=api_key,
                base_url=settings.base_url,
                model=settings.model,
                timeout=settings.timeout_seconds,
            ),
        )

    raise RankerConfigError(f"unsupported ranker provider: {provider}")
