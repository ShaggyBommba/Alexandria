"""FastAPI endpoint for parser service actions."""

from __future__ import annotations

from contextlib import asynccontextmanager
from logging import getLogger
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from application.app import App, get_app
from infrastructure.config import get_settings
from domain.exceptions import BaseError
from presentation.contracts import (
    IngestRequest,
    IngestResponse,
    RetrieveRequest,
    RetrieveResponse,
    error_payload,
)

logger = getLogger(__name__)


@asynccontextmanager
async def lifespan(api: FastAPI) -> AsyncGenerator[None, None]:
    """Handles initialization and cleanup logic for the API lifecycle."""
    if getattr(api.state, "app", None) is None:
        api.state.app = get_app()
    yield


@asynccontextmanager
async def scoped(request: Request) -> AsyncGenerator[App, None]:
    """Yield an app with request-scoped workflow sessions."""
    injected: App | None = getattr(request.app.state, "scoped", None)
    if injected is not None:
        yield injected
        return

    app = App(request.app.state.settings)
    try:
        yield app
    finally:
        app.close()


def validation_detail(exc: ValidationError) -> list[dict[str, object]]:
    """Return FastAPI-safe validation details."""
    return [
        {
            "loc": error.get("loc", ()),
            "msg": error.get("msg", "invalid input"),
            "type": error.get("type", "value_error"),
        }
        for error in exc.errors()
    ]


def api(app: App | None = None) -> FastAPI:
    settings = get_settings()

    api = FastAPI(
        title="alexandria-parser",
        version=settings.app.app_version,
        debug=settings.app.debug,
        lifespan=lifespan,
    )
    api.state.app = app
    api.state.scoped = app
    api.state.settings = settings

    @api.get("/health")
    def health(request: Request) -> dict[str, bool]:
        app: App = request.app.state.app
        return {"healthy": app.health}

    @api.get("/version")
    def version(request: Request) -> dict[str, str]:
        app: App = request.app.state.app
        return {"version": app.version}

    @api.post("/ingest", response_model=IngestResponse)
    async def ingest(
        request: Request,
        payload: IngestRequest,
    ):
        try:
            async with scoped(request) as app:
                id = await app.ingest(payload.doc())
        except BaseError as exc:
            return JSONResponse(status_code=400, content=error_payload(exc))

        return IngestResponse(id=id)

    @api.get("/retrieve", response_model=RetrieveResponse)
    async def retrieve(
        request: Request,
        query: str = Query(...),
        limit: int = Query(10),
    ):
        try:
            payload = RetrieveRequest(query=query, limit=limit)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=validation_detail(exc)) from exc

        try:
            async with scoped(request) as app:
                hits = await app.retrieve(payload.query, limit=payload.limit)
        except BaseError as exc:
            return JSONResponse(status_code=400, content=error_payload(exc))

        return RetrieveResponse.from_hits(hits)

    return api


def main() -> None:
    settings = get_settings()

    uvicorn.run(
        "presentation.api.app:api",
        factory=True,
        host=settings.app.api_host,
        port=settings.app.api_port,
        reload=True,
    )


if __name__ == "__main__":
    logger.info("Starting API service...")
    main()
