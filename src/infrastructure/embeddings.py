from __future__ import annotations

from collections.abc import Callable
from logging import getLogger
from typing import Protocol

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError
from openai.types import CreateEmbeddingResponse

from application.ports import Embedder as EmbedderPort
from infrastructure.config import EmbeddingProvider, EmbeddingSettings
from infrastructure.exceptions import (
    EmbedderClientError,
    EmbedderConfigError,
    EmbedderRequestError,
    EmbedderResponseError,
)

logging = getLogger(__name__)


class EmbeddingsResource(Protocol):
    """OpenAI SDK embeddings resource used by the adapter."""

    async def create(self, **kwargs: object) -> CreateEmbeddingResponse: ...


class OpenAIClient(Protocol):
    """Subset of the OpenAI SDK client used by the adapter."""

    embeddings: EmbeddingsResource


class OpenAIEmbedder:
    """Embeds text through the OpenAI SDK."""

    def __init__(
        self,
        settings: EmbeddingSettings,
        client: OpenAIClient | None = None,
    ) -> None:
        self.settings = settings
        api_key = (settings.api_key or "").strip()
        if client is None and not api_key:
            raise EmbedderConfigError("embedding provider openai requires an api_key")
        self.client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
        )

    async def embed(self, text: str) -> list[float]:
        """Return one embedding vector for the provided text."""
        request: dict[str, object] = {
            "input": text,
            "model": self.settings.model,
        }
        if self.settings.dimensions is not None:
            request["dimensions"] = self.settings.dimensions

        try:
            response = await self.client.embeddings.create(**request)
        except RateLimitError as exc:
            raise EmbedderClientError(str(exc)) from exc
        except APIConnectionError as exc:
            raise EmbedderClientError(str(exc)) from exc
        except APIStatusError as exc:
            if exc.status_code >= 500:
                raise EmbedderClientError(str(exc)) from exc
            raise EmbedderRequestError(str(exc)) from exc

        embedding = self.embedding(response)
        self.validate_dimensions(embedding)
        logging.debug(
            "embedding generated provider=%s model=%s dimensions=%s",
            self.settings.provider,
            self.settings.model,
            len(embedding),
        )
        return embedding

    def embedding(self, response: CreateEmbeddingResponse) -> list[float]:
        if not response.data:
            raise EmbedderResponseError("embedding endpoint returned no embeddings")
        embedding = list(response.data[0].embedding)
        if not embedding:
            raise EmbedderResponseError("embedding endpoint returned an empty vector")
        return embedding

    def validate_dimensions(self, embedding: list[float]) -> None:
        if self.settings.dimensions is None:
            return
        if len(embedding) != self.settings.dimensions:
            message = (
                f"embedding endpoint returned {len(embedding)} dimensions; "
                f"expected {self.settings.dimensions}"
            )
            raise EmbedderResponseError(message)


class LazyEmbedder:
    """Defer embedder construction until embeddings are first requested."""

    def __init__(self, factory: Callable[[], EmbedderPort]) -> None:
        self._factory = factory
        self._instance: EmbedderPort | None = None

    async def embed(self, text: str) -> list[float]:
        if self._instance is None:
            self._instance = self._factory()
        return await self._instance.embed(text)


def make_embedder(
    provider: EmbeddingProvider,
    settings: EmbeddingSettings,
) -> EmbedderPort:
    """Return the embedder adapter for one configured provider."""
    if provider is EmbeddingProvider.OPENAI:
        return OpenAIEmbedder(settings)
    raise EmbedderConfigError(f"unsupported embedding provider: {provider}")
