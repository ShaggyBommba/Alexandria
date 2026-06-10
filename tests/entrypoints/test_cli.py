from __future__ import annotations

import json
from uuid import UUID

from click.testing import CliRunner

from application.exceptions import AppError
from application.ports import DocHit, DocIn
from domain.entity import Document
from presentation.cli import app as cli_module


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
    version = "test-version"

    def __init__(self) -> None:
        self.ingest_calls: list[DocIn] = []
        self.retrieve_calls: list[tuple[str, int]] = []
        self.ingest_error: AppError | None = None
        self.retrieve_error: AppError | None = None

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


def run(app: FakeApp, args: list[str], monkeypatch):
    monkeypatch.setattr(cli_module, "get_app", lambda: app)
    return CliRunner().invoke(cli_module.cli, args)


def test_cli_ingest_prints_created_document_id(monkeypatch) -> None:
    # Arrange
    app = FakeApp()

    # Act
    result = run(
        app,
        ["ingest", "--name", " Alpha ", "--body", " Body ", "--source-key", " "],
        monkeypatch,
    )

    # Assert
    assert result.exit_code == 0
    assert result.output.strip() == str(uid(1))
    assert app.ingest_calls == [DocIn(name="Alpha", body="Body", source_key=None)]


def test_cli_retrieve_prints_deterministic_json(monkeypatch) -> None:
    # Arrange
    app = FakeApp()

    # Act
    result = run(app, ["retrieve", " alpha ", "--limit", "3"], monkeypatch)

    # Assert
    assert result.exit_code == 0
    assert json.loads(result.output) == {
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


def test_cli_validates_user_input(monkeypatch) -> None:
    # Arrange
    app = FakeApp()

    # Act
    ingest_result = run(
        app,
        ["ingest", "--name", " ", "--body", "Body"],
        monkeypatch,
    )
    retrieve_result = run(app, ["retrieve", "alpha", "--limit", "0"], monkeypatch)

    # Assert
    assert ingest_result.exit_code != 0
    assert "value must not be blank" in ingest_result.output
    assert retrieve_result.exit_code != 0
    assert "greater than or equal to 1" in retrieve_result.output
    assert app.ingest_calls == []
    assert app.retrieve_calls == []


def test_cli_translates_application_errors(monkeypatch) -> None:
    # Arrange
    app = FakeApp()
    app.ingest_error = PublicError("cannot ingest")
    app.retrieve_error = PublicError("cannot retrieve")

    # Act
    ingest_result = run(
        app,
        ["ingest", "--name", "Alpha", "--body", "Body"],
        monkeypatch,
    )
    retrieve_result = run(app, ["retrieve", "alpha"], monkeypatch)

    # Assert
    assert ingest_result.exit_code != 0
    assert "cannot ingest" in ingest_result.output
    assert retrieve_result.exit_code != 0
    assert "cannot retrieve" in retrieve_result.output
