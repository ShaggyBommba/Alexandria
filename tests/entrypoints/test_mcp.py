from __future__ import annotations

from uuid import UUID

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from application.exceptions import AppError
from application.ports import DocHit, DocIn
from domain.entity import Document
from infrastructure.exceptions import EmbedderClientError, SummarizerConfigError
from presentation.mcp.app import mcp


class PublicError(AppError):
    code = "app.public"


def uid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012x}")


def hit() -> DocHit:
    return DocHit(
        doc=Document(
            id=uid(10),
            leaf_id=uid(20),
            source_key="source:alpha",
            name="Alpha",
            summary="Alpha summary.",
            body="Alpha body.",
            embedding=[0.1],
        ),
        score=0.7,
        distance=0.3,
        bm25=None,
    )


class FakeSettings:
    class AppSettings:
        mcp_host = "localhost"
        mcp_port = 9002
        debug = False

    app = AppSettings()


class FakeApp:
    settings = FakeSettings()

    def __init__(self) -> None:
        self.ingest_calls: list[DocIn] = []
        self.retrieve_calls: list[tuple[str, int]] = []
        self.ingest_error: Exception | None = None
        self.retrieve_error: Exception | None = None

    async def ingest(self, doc: DocIn) -> UUID:
        self.ingest_calls.append(doc)
        if self.ingest_error is not None:
            raise self.ingest_error
        return uid(1)

    async def retrieve(self, query: str, limit: int = 10) -> list[DocHit]:
        self.retrieve_calls.append((query, limit))
        if self.retrieve_error is not None:
            raise self.retrieve_error
        return [hit()]


@pytest.mark.asyncio
async def test_mcp_registers_workflow_tools() -> None:
    # Arrange
    server = mcp(FakeApp())

    # Act
    tools = await server.list_tools()

    # Assert
    assert {tool.name for tool in tools} >= {"ingest", "retrieve"}


@pytest.mark.asyncio
async def test_mcp_ingest_validates_and_calls_app_with_doc_in() -> None:
    # Arrange
    app = FakeApp()
    server = mcp(app)

    # Act
    result = await server.call_tool(
        "ingest",
        {"name": " Alpha ", "body": "\n  Body\n", "source_key": " "},
    )

    # Assert
    assert result[1] == {"id": str(uid(1))}
    assert app.ingest_calls == [
        DocIn(name="Alpha", body="\n  Body\n", source_key=None)
    ]


@pytest.mark.asyncio
async def test_mcp_retrieve_returns_public_hit_data() -> None:
    # Arrange
    app = FakeApp()
    server = mcp(app)

    # Act
    result = await server.call_tool("retrieve", {"query": " alpha ", "limit": 3})

    # Assert
    assert result[1] == {
        "hits": [
            {
                "id": str(uid(10)),
                "leaf_id": str(uid(20)),
                "source_key": "source:alpha",
                "name": "Alpha",
                "summary": "Alpha summary.",
                "body": "Alpha body.",
                "score": 0.7,
                "distance": 0.3,
                "bm25": None,
            }
        ]
    }
    assert app.retrieve_calls == [("alpha", 3)]


@pytest.mark.asyncio
async def test_mcp_translates_validation_errors_to_tool_errors() -> None:
    # Arrange
    app = FakeApp()
    server = mcp(app)

    # Act / Assert
    with pytest.raises(ToolError, match="value must not be blank"):
        await server.call_tool("ingest", {"name": " ", "body": "Body"})
    with pytest.raises(ToolError, match="value must not be blank"):
        await server.call_tool("ingest", {"name": "Alpha", "body": " "})
    with pytest.raises(ToolError, match="greater than or equal to 1"):
        await server.call_tool("retrieve", {"query": "alpha", "limit": 0})

    assert app.ingest_calls == []
    assert app.retrieve_calls == []


@pytest.mark.asyncio
async def test_mcp_translates_application_errors_to_tool_errors() -> None:
    # Arrange
    app = FakeApp()
    app.ingest_error = PublicError("cannot ingest")
    app.retrieve_error = PublicError("cannot retrieve")
    server = mcp(app)

    # Act / Assert
    with pytest.raises(ToolError, match="app.public: cannot ingest"):
        await server.call_tool("ingest", {"name": "Alpha", "body": "Body"})
    with pytest.raises(ToolError, match="app.public: cannot retrieve"):
        await server.call_tool("retrieve", {"query": "alpha"})


@pytest.mark.asyncio
async def test_mcp_translates_expected_infrastructure_errors_to_tool_errors() -> None:
    # Arrange
    app = FakeApp()
    app.ingest_error = SummarizerConfigError("missing summarizer key")
    app.retrieve_error = EmbedderClientError("embedding unavailable")
    server = mcp(app)

    # Act / Assert
    with pytest.raises(ToolError, match="infra.summarizer.config: missing"):
        await server.call_tool("ingest", {"name": "Alpha", "body": "Body"})
    with pytest.raises(ToolError, match="infra.embedder.client: embedding"):
        await server.call_tool("retrieve", {"query": "alpha"})
