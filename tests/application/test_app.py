from __future__ import annotations

from application.app import App
from infrastructure.config import IngestSettings, Settings


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


class FakeSummarizer:
    pass


def test_app_wires_route_with_node_repository(monkeypatch) -> None:
    # Arrange
    import application.app as app_module

    monkeypatch.setattr(app_module, "Db", FakeDb)
    monkeypatch.setattr(app_module, "NodeRepo", FakeNodeRepo)
    monkeypatch.setattr(app_module, "OutboxRepo", FakeOutboxRepo)
    monkeypatch.setattr(app_module, "make_embedder", lambda provider, settings: FakeEmbedder())
    fake_summarizer = FakeSummarizer()
    monkeypatch.setattr(
        app_module,
        "make_summarizer",
        lambda provider, settings: fake_summarizer,
    )

    # Act
    settings = Settings(_env_file=None, ingest=IngestSettings(max_leaf_docs=7))
    app = App(settings)

    # Assert
    assert isinstance(app.nodes, FakeNodeRepo)
    assert app.nodes.session is app.session
    assert app.route_case.nodes is app.nodes
    assert app.ingest_case.route is app.route_case
    assert app.ingest_case.summarizer is fake_summarizer
    assert app.ingest_case.max_leaf_docs == 7
    assert app.retrieve_case.route is app.route_case
