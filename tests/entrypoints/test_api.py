from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from application.exceptions import AppError
from application.ports import DocHit, DocIn
from infrastructure.config import Settings
from infrastructure.exceptions import EmbedderClientError, SummarizerConfigError
from domain.entity import Document
from presentation.api import app as api_module
from presentation.api.app import api


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


class FakeApp:
    health = True
    version = "test-version"

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


def client(app: FakeApp) -> TestClient:
    return TestClient(api(app))


def test_api_keeps_health_and_version_working() -> None:
    # Arrange
    app = FakeApp()

    # Act / Assert
    with client(app) as item:
        assert item.get("/health").json() == {"healthy": True}
        assert item.get("/version").json() == {"version": "test-version"}


def test_api_metadata_routes_do_not_construct_workflow_app(monkeypatch) -> None:
    # Arrange
    class ExplodingApp:
        def __init__(self, _settings: Settings) -> None:
            raise AssertionError("metadata route constructed App")

    monkeypatch.setattr(api_module, "App", ExplodingApp)
    monkeypatch.setattr(
        api_module,
        "get_settings",
        lambda: Settings(_env_file=None),
    )

    # Act / Assert
    with TestClient(api_module.api()) as item:
        assert item.get("/health").json() == {"healthy": True}
        assert item.get("/version").json() == {"version": "0.1.0"}


def test_api_ingest_validates_and_calls_app_with_doc_in() -> None:
    # Arrange
    app = FakeApp()

    # Act
    with client(app) as item:
        response = item.post(
            "/ingest",
            json={"name": " Alpha ", "body": "\n  Body\n", "source_key": " "},
        )

    # Assert
    assert response.status_code == 200
    assert response.json() == {"id": str(uid(1))}
    assert app.ingest_calls == [
        DocIn(name="Alpha", body="\n  Body\n", source_key=None)
    ]


def test_api_retrieve_returns_public_hit_data() -> None:
    # Arrange
    app = FakeApp()

    # Act
    with client(app) as item:
        response = item.get("/retrieve", params={"query": " alpha ", "limit": 3})

    # Assert
    assert response.status_code == 200
    assert response.json() == {
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


def test_api_rejects_invalid_public_inputs() -> None:
    # Arrange
    app = FakeApp()

    # Act / Assert
    with client(app) as item:
        ingest_response = item.post("/ingest", json={"name": " ", "body": "Body"})
        body_response = item.post("/ingest", json={"name": "Alpha", "body": " "})
        retrieve_response = item.get("/retrieve", params={"query": " ", "limit": 0})

    assert ingest_response.status_code == 422
    assert body_response.status_code == 422
    assert retrieve_response.status_code == 422
    assert app.ingest_calls == []
    assert app.retrieve_calls == []


def test_api_translates_application_errors() -> None:
    # Arrange
    app = FakeApp()
    app.ingest_error = PublicError("cannot ingest")
    app.retrieve_error = PublicError("cannot retrieve")

    # Act / Assert
    with client(app) as item:
        ingest_response = item.post(
            "/ingest",
            json={"name": "Alpha", "body": "Body"},
        )
        retrieve_response = item.get("/retrieve", params={"query": "alpha"})

    assert ingest_response.status_code == 400
    assert ingest_response.json() == {
        "error": {"code": "app.public", "message": "cannot ingest"}
    }
    assert retrieve_response.status_code == 400
    assert retrieve_response.json() == {
        "error": {"code": "app.public", "message": "cannot retrieve"}
    }


def test_api_translates_expected_infrastructure_errors() -> None:
    # Arrange
    app = FakeApp()
    app.ingest_error = SummarizerConfigError("missing summarizer key")
    app.retrieve_error = EmbedderClientError("embedding unavailable")

    # Act / Assert
    with client(app) as item:
        ingest_response = item.post(
            "/ingest",
            json={"name": "Alpha", "body": "Body"},
        )
        retrieve_response = item.get("/retrieve", params={"query": "alpha"})

    assert ingest_response.status_code == 400
    assert ingest_response.json() == {
        "error": {
            "code": "infra.summarizer.config",
            "message": "missing summarizer key",
        }
    }
    assert retrieve_response.status_code == 400
    assert retrieve_response.json() == {
        "error": {
            "code": "infra.embedder.client",
            "message": "embedding unavailable",
        }
    }


def test_api_uses_request_scoped_apps_for_real_workflows(monkeypatch) -> None:
    # Arrange
    instances: list[ScopedApp] = []

    class ScopedApp(FakeApp):
        def __init__(self, settings: Settings) -> None:
            super().__init__()
            self.settings = settings
            self.closed = False
            instances.append(self)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(api_module, "App", ScopedApp)

    # Act
    with TestClient(api_module.api()) as item:
        ingest_response = item.post(
            "/ingest",
            json={"name": "Alpha", "body": "Body"},
        )
        retrieve_response = item.get("/retrieve", params={"query": "alpha"})

    # Assert
    assert ingest_response.status_code == 200
    assert retrieve_response.status_code == 200
    assert len(instances) == 2
    assert all(instance.closed for instance in instances)
    assert instances[0].ingest_calls == [DocIn(name="Alpha", body="Body")]
    assert instances[1].retrieve_calls == [("alpha", 10)]
