from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from application.app import App
import application.app as app_module
from application.ports import DocIn
from domain.entity import Base, VECTOR_DIMENSIONS
from infrastructure.config import IngestSettings, Settings
from presentation.api.app import api


class MemoryDb:
    def __init__(self) -> None:
        self._engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self._sessions = sessionmaker(bind=self._engine)

    def sessions(self) -> sessionmaker[Session]:
        return self._sessions

    def session(self) -> Session:
        return self._sessions()

    def create_all(self) -> None:
        Base.metadata.create_all(self._engine)


class FakeEmbedder:
    def __init__(self, embed: Callable[[str], list[float]]) -> None:
        self.embed_text = embed
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return self.embed_text(text)


class FakeSummarizer:
    def __init__(self, summaries: dict[str, str]) -> None:
        self.summaries = summaries
        self.calls: list[DocIn] = []

    async def summarize(self, doc: DocIn) -> str:
        self.calls.append(doc)
        return self.summaries[doc.name]


def vector(*values: float) -> list[float]:
    embedding = [0.0] * VECTOR_DIMENSIONS
    for index, value in enumerate(values):
        embedding[index] = value
    return embedding


def deterministic_embedding(text: str) -> list[float]:
    lowered = text.lower()
    if "alpha" in lowered:
        return vector(1.0, 0.0)
    if "beta" in lowered:
        return vector(0.0, 1.0)
    return vector(0.0, 0.0, 1.0)


def make_app(monkeypatch) -> tuple[App, FakeEmbedder, FakeSummarizer]:
    db = MemoryDb()
    embedder = FakeEmbedder(deterministic_embedding)
    summarizer = FakeSummarizer(
        {
            "Alpha": "Alpha summary.",
            "Beta": "Beta summary.",
        }
    )

    monkeypatch.setattr(app_module, "Db", lambda _settings: db)
    monkeypatch.setattr(
        app_module,
        "make_embedder",
        lambda _provider, _settings: embedder,
    )
    monkeypatch.setattr(
        app_module,
        "make_summarizer",
        lambda _provider, _settings: summarizer,
    )

    settings = Settings(_env_file=None, ingest=IngestSettings(max_leaf_docs=100))
    return App(settings), embedder, summarizer


def test_api_public_boundary_ingests_and_retrieves_local_documents(
    monkeypatch,
) -> None:
    # Arrange
    app, embedder, summarizer = make_app(monkeypatch)

    # Act
    with TestClient(api(app)) as client:
        alpha_response = client.post(
            "/ingest",
            json={
                "name": "Alpha",
                "body": "alpha retrieval notes",
                "source_key": "source:alpha",
            },
        )
        beta_response = client.post(
            "/ingest",
            json={
                "name": "Beta",
                "body": "beta retrieval notes",
                "source_key": "source:beta",
            },
        )
        retrieve_response = client.get(
            "/retrieve",
            params={"query": "alpha retrieval query", "limit": 2},
        )

    # Assert
    assert alpha_response.status_code == 200
    assert beta_response.status_code == 200
    assert retrieve_response.status_code == 200

    alpha_id = alpha_response.json()["id"]
    beta_id = beta_response.json()["id"]
    payload = retrieve_response.json()

    assert [hit["id"] for hit in payload["hits"]] == [alpha_id, beta_id]
    assert [hit["source_key"] for hit in payload["hits"]] == [
        "source:alpha",
        "source:beta",
    ]
    assert [hit["name"] for hit in payload["hits"]] == ["Alpha", "Beta"]
    assert payload["hits"][0]["score"] == 0.4
    assert payload["hits"][0]["distance"] == 0.0
    assert payload["hits"][0]["bm25"] is not None

    assert "alpha retrieval query" in embedder.calls
    assert summarizer.calls == [
        DocIn(
            name="Alpha",
            body="alpha retrieval notes",
            source_key="source:alpha",
        ),
        DocIn(
            name="Beta",
            body="beta retrieval notes",
            source_key="source:beta",
        ),
    ]
