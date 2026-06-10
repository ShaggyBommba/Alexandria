"""MCP tools for Alexandria public workflows."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from application.app import App, get_app
from application.exceptions import AppError
from infrastructure.config import get_settings
from presentation.contracts import (
    IngestRequest,
    IngestResponse,
    RetrieveRequest,
    RetrieveResponse,
    validation_message,
)


def tool_error(exc: AppError | ValidationError) -> ValueError:
    """Convert expected public failures into MCP tool errors."""
    if isinstance(exc, ValidationError):
        return ValueError(validation_message(exc))
    return ValueError(f"{exc.code}: {exc}")


def mcp(app: App | None = None) -> FastMCP:
    """Build the MCP server with workflow tools."""
    settings = app.settings if app is not None else get_settings()
    server = FastMCP(
        "alexandria",
        host=settings.app.mcp_host,
        port=settings.app.mcp_port,
        debug=settings.app.debug,
    )

    def current_app() -> App:
        return app if app is not None else get_app()

    @server.tool(structured_output=True)
    async def ingest(
        name: str,
        body: str,
        source_key: str | None = None,
    ) -> dict[str, object]:
        """Ingest one document and return its id."""
        try:
            payload = IngestRequest(name=name, body=body, source_key=source_key)
            id = await current_app().ingest(payload.doc())
        except (AppError, ValidationError) as exc:
            raise tool_error(exc) from exc

        return IngestResponse(id=id).model_dump(mode="json")

    @server.tool(structured_output=True)
    async def retrieve(query: str, limit: int = 10) -> dict[str, object]:
        """Retrieve document hits for one query."""
        try:
            payload = RetrieveRequest(query=query, limit=limit)
            hits = await current_app().retrieve(payload.query, limit=payload.limit)
        except (AppError, ValidationError) as exc:
            raise tool_error(exc) from exc

        return RetrieveResponse.from_hits(hits).model_dump(mode="json")

    return server


def main() -> None:
    mcp().run(transport="streamable-http")


if __name__ == "__main__":
    main()
