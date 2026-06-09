"""FastAPI endpoint for parser service actions."""

from __future__ import annotations

from contextlib import asynccontextmanager
from logging import getLogger
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request

from application.app import App, get_app
from infrastructure.config import get_settings

logger = getLogger(__name__)

@asynccontextmanager
async def lifespan(api: FastAPI) -> AsyncGenerator[None, None]:
    """Handles initialization and cleanup logic for the API lifecycle."""
    api.state.app = get_app()
    yield


def api() -> FastAPI:
    settings = get_settings()

    api = FastAPI(
        title="alexandria-parser",
        version=settings.app.app_version,
        debug=settings.app.debug,
        lifespan=lifespan,
    )

    @api.get("/health")
    def health(request: Request) -> dict[str, bool]:
        app: App = request.app.state.app
        return {"healthy": app.health}

    @api.get("/version")
    def version(request: Request) -> dict[str, str]:
        app: App = request.app.state.app
        return {"version": app.version}

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
