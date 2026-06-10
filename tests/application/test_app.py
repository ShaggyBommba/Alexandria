from __future__ import annotations

import pytest

from application.app import App
from infrastructure.config import IngestSettings, Settings


class FakeDb:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.read_session = object()
        self.unit_of_work_session = object()
        self.unit_of_work_session_factory = FakeSessionFactory(
            self.unit_of_work_session
        )
        self.created = False
        self.sessions_called = False
        self.session_called = False

    def sessions(self):
        self.sessions_called = True
        return self.unit_of_work_session_factory

    def session(self):
        self.session_called = True
        return self.read_session

    def create_all(self) -> None:
        self.created = True


class FakeSessionFactory:
    def __init__(self, session) -> None:
        self.session = session
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.session


class FakeNodeRepo:
    def __init__(self, session) -> None:
        self.session = session


class FakeReferenceRepo:
    def __init__(self, session) -> None:
        self.session = session


class FakeSqlSearch:
    def __init__(self, session) -> None:
        self.session = session


class FakeSqlUnitOfWork:
    def __init__(self, sessions, queue=None) -> None:
        self.received_sessions = sessions
        self.received_queue = queue
        self.nodes = object()
        self.docs = object()
        self.refs = object()
        self.outbox = object()

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FakeEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [len(text)]


class DeferredSummarizer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def summarize(self, _doc) -> str:
        self.calls.append("summarize")
        return "ok"


class FakeSummarizer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def summarize(self, doc) -> str:
        self.calls.append("summarize")
        return f"summary:{doc.body}"


class MockDoc:
    def __init__(self) -> None:
        self.name = "doc"
        self.body = "body"
        self.source_key = "source"


class FakeSummarizerWrapper:
    def __init__(self, target) -> None:
        self.target = target


def test_app_wires_read_and_write_dependencies_with_a_session_factory(
    monkeypatch,
) -> None:
    # Arrange
    import application.app as app_module

    fake_db = FakeDb(Settings())
    factory_calls: list[str] = []
    deferred_summarizer = DeferredSummarizer()

    monkeypatch.setattr(app_module, "Db", lambda settings: fake_db)
    monkeypatch.setattr(app_module, "NodeRepo", FakeNodeRepo)
    monkeypatch.setattr(app_module, "ReferenceRepo", FakeReferenceRepo)
    monkeypatch.setattr(app_module, "SqlSearch", FakeSqlSearch)
    monkeypatch.setattr(app_module, "SqlUnitOfWork", FakeSqlUnitOfWork)
    monkeypatch.setattr(
        app_module, "make_embedder", lambda provider, settings: FakeEmbedder()
    )

    def make_summarizer_factory(_provider, _settings):
        factory_calls.append("called")
        return deferred_summarizer

    monkeypatch.setattr(app_module, "make_summarizer", make_summarizer_factory)

    # Act
    settings = Settings(_env_file=None, ingest=IngestSettings(max_leaf_docs=7))
    app = App(settings)

    # Assert
    assert fake_db.created
    assert fake_db.sessions_called
    assert fake_db.session_called
    assert app.sessions is fake_db.unit_of_work_session_factory
    assert isinstance(app.nodes, FakeNodeRepo)
    assert app.nodes.session is fake_db.read_session
    assert app.nodes.session is app.session
    assert isinstance(app.refs_repo, FakeReferenceRepo)
    assert app.refs_repo.session is fake_db.read_session
    assert isinstance(app.search, FakeSqlSearch)
    assert app.search.session is fake_db.read_session
    assert isinstance(app.uow, FakeSqlUnitOfWork)
    assert app.uow.received_sessions is fake_db.unit_of_work_session_factory
    assert app.uow.received_queue == settings.queue
    assert app.queue is app.outbox is app.uow.outbox

    assert app.seed_case.uow is app.uow
    assert app.route_case.nodes is app.nodes
    assert app.ingest_case.uow is app.uow
    assert app.ingest_case.route is app.route_case
    assert app.ingest_case.summarizer is app.summarizer
    assert app.ingest_case.seed is app.seed_case
    assert app.ingest_case.max_leaf_docs == 7
    assert app.ingest_case.summarizer is app.summarizer
    assert app.retrieve_case.route is app.route_case
    assert app.retrieve_case.refs is app.refs_repo
    assert app.retrieve_case.search is app.search
    assert app.retrieve_case.embedder is app.embedder
    assert app.rerank_case is app.retrieve_case.rerank
    assert app.refs_case.uow is app.uow
    assert app.lint_case.uow is app.uow
    assert app.lint_case.split is app.split_case
    assert app.split_case.uow is app.uow
    assert factory_calls == []


@pytest.mark.asyncio
async def test_app_constructs_summarizer_on_first_use(monkeypatch) -> None:
    # Arrange
    import application.app as app_module

    fake_db = FakeDb(Settings())
    deferred = DeferredSummarizer()

    monkeypatch.setattr(app_module, "Db", lambda settings: fake_db)
    monkeypatch.setattr(app_module, "NodeRepo", FakeNodeRepo)
    monkeypatch.setattr(app_module, "ReferenceRepo", FakeReferenceRepo)
    monkeypatch.setattr(app_module, "SqlSearch", FakeSqlSearch)
    monkeypatch.setattr(app_module, "SqlUnitOfWork", FakeSqlUnitOfWork)
    monkeypatch.setattr(
        app_module, "make_embedder", lambda provider, settings: FakeEmbedder()
    )
    monkeypatch.setattr(
        app_module, "make_summarizer", lambda _provider, _settings: deferred
    )

    settings = Settings(_env_file=None, ingest=IngestSettings(max_leaf_docs=7))
    app = App(settings)

    # Act
    await app.summarizer.summarize(MockDoc())

    # Assert
    assert deferred.calls == ["summarize"]
