from __future__ import annotations

import pytest

from application.app import App
from infrastructure.config import IngestSettings, Settings, SummarizerSettings


class FakeDb:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.opened_session = object()
        self.created = False

    def session(self):
        return self.opened_session

    def create_all(self) -> None:
        self.created = True


class FakeNodeRepo:
    def __init__(self, session) -> None:
        self.session = session


class FakeOutboxRepo:
    def __init__(self, session, settings) -> None:
        self.session = session
        self.settings = settings


class FakeEmbedder:
    pass


class DeferredSummarizer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def summarize(self, _doc) -> str:
        self.calls.append("summarize")
        return "ok"


def test_app_wires_route_with_node_repository(monkeypatch) -> None:
    # Arrange
    import application.app as app_module

    monkeypatch.setattr(app_module, "Db", FakeDb)
    monkeypatch.setattr(app_module, "NodeRepo", FakeNodeRepo)
    monkeypatch.setattr(app_module, "OutboxRepo", FakeOutboxRepo)
    monkeypatch.setattr(app_module, "make_embedder", lambda provider, settings: FakeEmbedder())
    factory_calls: list[str] = []
    deferred_summarizer = DeferredSummarizer()

    def make_lazy_summarizer(provider, settings):
        factory_calls.append("called")
        return deferred_summarizer

    monkeypatch.setattr(app_module, "make_summarizer", make_lazy_summarizer)

    # Act
    settings = Settings(_env_file=None, ingest=IngestSettings(max_leaf_docs=7))
    app = App(settings)

    # Assert
    assert isinstance(app.nodes, FakeNodeRepo)
    assert app.nodes.session is app.session
    assert app.route_case.nodes is app.nodes
    assert app.ingest_case.route is app.route_case
    assert app.ingest_case.summarizer is app.summarizer
    assert factory_calls == []
    assert app.ingest_case.max_leaf_docs == 7
    assert app.retrieve_case.route is app.route_case


@pytest.mark.asyncio
async def test_app_constructs_summarizer_on_first_use(monkeypatch) -> None:
    # Arrange
    import application.app as app_module

    monkeypatch.setattr(app_module, "Db", FakeDb)
    monkeypatch.setattr(app_module, "NodeRepo", FakeNodeRepo)
    monkeypatch.setattr(app_module, "OutboxRepo", FakeOutboxRepo)
    monkeypatch.setattr(app_module, "make_embedder", lambda provider, settings: FakeEmbedder())

    deferred = DeferredSummarizer()
    monkeypatch.setattr(
        app_module,
        "make_summarizer",
        lambda provider, settings: deferred,
    )

    settings = Settings(_env_file=None, ingest=IngestSettings(max_leaf_docs=7))
    app = App(settings)

    # Act
    await app.summarizer.summarize(object())

    # Assert
    assert deferred.calls == ["summarize"]


def test_app_initializes_without_immediate_summarizer_config(monkeypatch) -> None:
    # Arrange
    import application.app as app_module

    monkeypatch.setattr(app_module, "Db", FakeDb)
    monkeypatch.setattr(app_module, "NodeRepo", FakeNodeRepo)
    monkeypatch.setattr(app_module, "OutboxRepo", FakeOutboxRepo)
    monkeypatch.setattr(app_module, "make_embedder", lambda provider, settings: FakeEmbedder())

    # Act / Assert
    App(
        Settings(
            _env_file=None,
            ingest=IngestSettings(max_leaf_docs=7),
            summarizer=SummarizerSettings(),
        )
    )
