from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr
from openai import APIConnectionError, APIStatusError, RateLimitError
from openai.types import CreateEmbeddingResponse
from openai.types.embedding import Embedding

from application.ports import Embedder as EmbedderPort
from infrastructure.config import EmbeddingProvider, EmbeddingSettings
from infrastructure.embeddings import OpenAIEmbedder, make_embedder
from infrastructure.exceptions import (
    EmbedderClientError,
    EmbedderConfigError,
    EmbedderRequestError,
    EmbedderResponseError,
)


class FakeEmbeddings:
    def __init__(
        self,
        response: CreateEmbeddingResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or embedding_response([0.1, 0.2, 0.3])
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> CreateEmbeddingResponse:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, embeddings: FakeEmbeddings) -> None:
        self.embeddings = embeddings


def embedding_response(embedding: list[float]) -> CreateEmbeddingResponse:
    return CreateEmbeddingResponse(
        data=[Embedding(embedding=embedding, index=0, object="embedding")],
        model="text-embedding-3-small",
        object="list",
        usage={"prompt_tokens": 1, "total_tokens": 1},
    )


def status_error(status: int) -> APIStatusError:
    request = httpx.Request("POST", "http://localhost:1234/v1/embeddings")
    response = httpx.Response(status, request=request, text="provider error")
    return APIStatusError("provider error", response=response, body=None)


@pytest.mark.asyncio
async def test_embedder_uses_openai_sdk_embeddings_resource() -> None:
    # Arrange
    embeddings = FakeEmbeddings()
    client = FakeClient(embeddings)
    settings = EmbeddingSettings(
        base_url="http://localhost:1234/v1",
        api_key=SecretStr("test-key"),
        model="text-embedding-3-small",
        dimensions=3,
        timeout_seconds=5.0,
    )
    embedder = OpenAIEmbedder(settings, client)

    # Act
    embedding = await embedder.embed("hello")

    # Assert
    assert isinstance(embedder, EmbedderPort)
    assert embedding == pytest.approx([0.1, 0.2, 0.3])
    assert embeddings.calls == [
        {
            "input": "hello",
            "model": "text-embedding-3-small",
            "dimensions": 3,
        }
    ]


@pytest.mark.asyncio
async def test_embedder_omits_dimensions_when_not_configured() -> None:
    # Arrange
    embeddings = FakeEmbeddings()
    client = FakeClient(embeddings)
    settings = EmbeddingSettings(model="local-embedding-model")
    embedder = OpenAIEmbedder(settings, client)

    # Act
    await embedder.embed("local text")

    # Assert
    assert embeddings.calls == [
        {
            "input": "local text",
            "model": "local-embedding-model",
        }
    ]


def test_factory_returns_openai_embedder_for_provider_enum() -> None:
    # Arrange
    settings = EmbeddingSettings(
        provider=EmbeddingProvider.OPENAI, api_key=SecretStr("test-key")
    )

    # Act
    embedder = make_embedder(EmbeddingProvider.OPENAI, settings)

    # Assert
    assert isinstance(embedder, OpenAIEmbedder)
    assert isinstance(embedder, EmbedderPort)


@pytest.mark.parametrize("value", [None, SecretStr(""), SecretStr("   ")])
def test_factory_rejects_missing_or_blank_api_key(value: SecretStr | None) -> None:
    settings = EmbeddingSettings(provider=EmbeddingProvider.OPENAI, api_key=value)

    with pytest.raises(EmbedderConfigError, match="requires an api_key"):
        make_embedder(EmbeddingProvider.OPENAI, settings)


@pytest.mark.asyncio
async def test_embedder_rejects_empty_provider_data() -> None:
    # Arrange
    response = CreateEmbeddingResponse(
        data=[],
        model="text-embedding-3-small",
        object="list",
        usage={"prompt_tokens": 1, "total_tokens": 1},
    )
    embedder = OpenAIEmbedder(EmbeddingSettings(), FakeClient(FakeEmbeddings(response)))

    # Act / Assert
    with pytest.raises(EmbedderResponseError):
        await embedder.embed("hello")


@pytest.mark.asyncio
async def test_embedder_rejects_unexpected_dimensions() -> None:
    # Arrange
    embeddings = FakeEmbeddings(embedding_response([0.1, 0.2]))
    settings = EmbeddingSettings(dimensions=3)
    embedder = OpenAIEmbedder(settings, FakeClient(embeddings))

    # Act / Assert
    with pytest.raises(EmbedderResponseError):
        await embedder.embed("hello")


@pytest.mark.asyncio
async def test_embedder_maps_permanent_sdk_status_errors_to_request_errors() -> None:
    # Arrange
    embeddings = FakeEmbeddings(error=status_error(401))
    embedder = OpenAIEmbedder(EmbeddingSettings(), FakeClient(embeddings))

    # Act / Assert
    with pytest.raises(EmbedderRequestError):
        await embedder.embed("hello")


@pytest.mark.asyncio
async def test_embedder_maps_retryable_sdk_errors_to_client_errors() -> None:
    # Arrange
    request = httpx.Request("POST", "http://localhost:1234/v1/embeddings")
    response = httpx.Response(429, request=request, text="rate limited")
    embeddings = FakeEmbeddings(
        error=RateLimitError("rate limited", response=response, body=None)
    )
    embedder = OpenAIEmbedder(EmbeddingSettings(), FakeClient(embeddings))

    # Act / Assert
    with pytest.raises(EmbedderClientError):
        await embedder.embed("hello")


@pytest.mark.asyncio
async def test_embedder_maps_sdk_connection_errors_to_client_errors() -> None:
    # Arrange
    request = httpx.Request("POST", "http://localhost:1234/v1/embeddings")
    embeddings = FakeEmbeddings(
        error=APIConnectionError(message="connection failed", request=request)
    )
    embedder = OpenAIEmbedder(EmbeddingSettings(), FakeClient(embeddings))

    # Act / Assert
    with pytest.raises(EmbedderClientError):
        await embedder.embed("hello")
