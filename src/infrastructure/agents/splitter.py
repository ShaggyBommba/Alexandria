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
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator

from application.ports import ChildPlan, SplitPlan
from application.ports import Embedder as EmbedderPort
from application.ports import Splitter as SplitterPort
from domain.entity import Document, Node
from infrastructure.config import SplitterProvider, SplitterSettings
from infrastructure.exceptions import SplitterConfigError, SplitterError, SplitterResponseError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a splitting agent for Alexandria, a semantic wiki. Split one full "
    "leaf node into coherent child leaf nodes. The assignment is a strict "
    "partition: assign every supplied document to exactly one child, never "
    "repeat a document across children, and never leave a document unassigned."
)

USER_PROMPT = (
    "Return only the structured split plan. Use only the supplied document ids. "
    "Create at least two children and never more children than the number of "
    "documents. Assign each document id to exactly one child, with no "
    "duplicates and none left out. Each child needs a concise name, factual "
    "description, and its assigned document ids."
)


class SplitChildResult(BaseModel):
    """One structured child returned by a splitter provider."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    docs: list[UUID] = Field(min_length=1)

    @field_validator("name", "description")
    @classmethod
    def required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("value must not be blank")
        return text


class SplitResult(BaseModel):
    """Structured split plan returned by the LangChain agent."""

    children: list[SplitChildResult] = Field(min_length=1, max_length=10)

    def plan(self, embeddings: list[list[float]]) -> SplitPlan:
        """Convert provider output to the application split plan shape.

        Child embeddings are derived by the adapter from each child's
        description, not returned by the chat model.
        """
        return SplitPlan(
            children=[
                ChildPlan(
                    name=child.name,
                    description=child.description,
                    embedding=list(embedding),
                    docs=list(child.docs),
                )
                for child, embedding in zip(self.children, embeddings, strict=True)
            ]
        )


class LangSplitter:
    """LangChain adapter that proposes child leaves for a full source leaf."""

    def __init__(
        self,
        client: BaseChatModel,
        embedder: EmbedderPort,
        tools: Sequence[Any] | None = None,
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.tools = list(tools or [])

    @cached_property
    def agent(self) -> Runnable:
        """Create the LangChain agent graph."""
        return create_agent(
            model=self.client,
            tools=self.tools,
            response_format=SplitResult,
        )

    async def split(self, node: Node, docs: list[Document]) -> SplitPlan:
        """Request and validate one split plan through the configured agent."""
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                (
                    "human",
                    USER_PROMPT
                    + "\n\nNode id:\n{node_id}\n\nNode name:\n{name}"
                    + "\n\nNode description:\n{description}"
                    + "\n\nDocuments:\n{documents}",
                ),
            ]
        )
        messages = prompt.format_messages(
            node_id=str(node.id),
            name=node.name,
            description=node.description,
            documents=document(docs),
        )

        try:
            output = await self.agent.ainvoke({"messages": messages})
            result = self.parsed(output)
        except SplitterResponseError:
            raise
        except Exception as exc:
            raise SplitterError(f"Splitter agent execution failed: {exc}") from exc

        embeddings = [
            await self.embedder.embed(child.description) for child in result.children
        ]
        logger.debug("Agent returned split result: %s", result.model_dump_json(indent=2))
        return result.plan(embeddings)

    @staticmethod
    def parsed(output: Any) -> SplitResult:
        """Validate the structured response returned by the agent graph."""
        if isinstance(output, SplitResult):
            return output

        if not isinstance(output, Mapping):
            raise SplitterResponseError("Splitter agent returned an invalid response")

        if "structured_response" not in output:
            raise SplitterResponseError("Splitter agent returned no structured response")

        structured = output["structured_response"]
        try:
            return SplitResult.model_validate(structured)
        except ValidationError as exc:
            raise SplitterResponseError(
                f"Splitter agent returned invalid structured response: {exc}"
            ) from exc


def document(docs: list[Document]) -> str:
    """Return deterministic document context for the splitter prompt."""
    lines: list[str] = []
    for doc in sorted(docs, key=lambda item: str(item.id)):
        lines.append(
            "\n".join(
                [
                    f"Document id: {doc.id}",
                    f"Name: {doc.name}",
                    f"Summary: {doc.summary}",
                    f"Body: {doc.body}",
                ]
            )
        )
    return "\n\n---\n\n".join(lines)


def make_splitter(
    provider: SplitterProvider,
    settings: SplitterSettings,
    embedder: EmbedderPort,
) -> SplitterPort | None:
    """Build the configured splitter adapter, or disable it explicitly."""
    if provider is SplitterProvider.NONE:
        return None

    if provider is SplitterProvider.OPENAI:
        api_key: SecretStr | None = settings.api_key
        if api_key is None or not api_key.get_secret_value().strip():
            raise SplitterConfigError("splitter provider openai requires an api_key")

        return LangSplitter(
            client=ChatOpenAI(
                api_key=api_key,
                base_url=settings.base_url,
                model=settings.model,
                timeout=settings.timeout_seconds,
            ),
            embedder=embedder,
        )
    raise SplitterConfigError(f"unsupported splitter provider: {provider}")
