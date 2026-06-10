from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from domain.entity import Base, Job
from domain.values import JobKind, JobStatus
from infrastructure.config import Settings
from infrastructure.repositories.outbox import OutboxRepo
from presentation.worker.app import Worker
import presentation.worker.app as worker_module


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Job.__table__])
    try:
        yield sessionmaker(bind=engine)
    finally:
        Base.metadata.drop_all(engine, tables=[Job.__table__])
        engine.dispose()


def uid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012x}")


class FakeDb:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def sessions(self) -> sessionmaker[Session]:
        return self._sessions


class FakeApp:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.db = FakeDb(sessions)
        self.settings = Settings(_env_file=None)
        self.lint_calls: list[UUID] = []

    async def lint(self, node_id: UUID) -> None:
        self.lint_calls.append(node_id)


async def append(session_factory: sessionmaker[Session], job: Job) -> UUID:
    with session_factory() as session:
        repo = OutboxRepo(session)
        id = await repo.append(job)
        session.commit()
        return id


def row(session_factory: sessionmaker[Session], id: UUID) -> Job:
    with session_factory() as session:
        item = session.get(Job, id)
        assert item is not None
        return item


@pytest.mark.asyncio
async def test_worker_marks_malformed_split_check_payload_failed(
    sessions: sessionmaker[Session],
) -> None:
    # Arrange
    app = FakeApp(sessions)
    job_id = await append(
        sessions,
        Job(kind=JobKind.SPLIT_CHECK, payload={"node_id": "not-a-uuid"}),
    )
    worker = Worker(app=app, kind=JobKind.SPLIT_CHECK)

    # Act
    processed = await worker.batch()

    # Assert
    saved = row(sessions, job_id)
    assert processed == 1
    assert app.lint_calls == []
    assert saved.status == JobStatus.FAILED.value
    assert saved.attempts == 1
    assert saved.last_error == "split.check payload requires node_id UUID"


@pytest.mark.asyncio
async def test_worker_marks_non_object_split_check_payload_failed(
    sessions: sessionmaker[Session],
) -> None:
    # Arrange
    app = FakeApp(sessions)
    job_id = await append(
        sessions,
        Job(kind=JobKind.SPLIT_CHECK, payload="not-an-object"),
    )
    worker = Worker(app=app, kind=JobKind.SPLIT_CHECK)

    # Act
    processed = await worker.batch()

    # Assert
    saved = row(sessions, job_id)
    assert processed == 1
    assert app.lint_calls == []
    assert saved.status == JobStatus.FAILED.value
    assert saved.attempts == 1
    assert saved.last_error == "split.check payload requires node_id UUID"


@pytest.mark.asyncio
async def test_worker_marks_successful_split_check_job_done(
    sessions: sessionmaker[Session],
) -> None:
    # Arrange
    app = FakeApp(sessions)
    node_id = uid(1)
    job_id = await append(
        sessions,
        Job(kind=JobKind.SPLIT_CHECK, payload={"node_id": str(node_id)}),
    )
    worker = Worker(app=app, kind=JobKind.SPLIT_CHECK)

    # Act
    processed = await worker.batch()

    # Assert
    saved = row(sessions, job_id)
    assert processed == 1
    assert app.lint_calls == [node_id]
    assert saved.status == JobStatus.DONE.value
    assert saved.done_at is not None
    assert saved.last_error is None


@pytest.mark.asyncio
async def test_worker_does_not_commit_claim_before_handling(monkeypatch) -> None:
    # Arrange
    events: list[str] = []
    node_id = uid(1)

    class RecordingSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def commit(self) -> None:
            events.append("commit")

        def rollback(self) -> None:
            events.append("rollback")

    class RecordingSessions:
        def __call__(self) -> RecordingSession:
            return RecordingSession()

    class RecordingDb:
        def sessions(self) -> RecordingSessions:
            return RecordingSessions()

    class RecordingApp:
        def __init__(self) -> None:
            self.db = RecordingDb()
            self.settings = Settings(_env_file=None)

        async def lint(self, id: UUID) -> None:
            assert "commit" not in events
            events.append("lint")
            assert id == node_id

    class RecordingOutbox:
        def __init__(self, _session, _queue) -> None:
            return None

        async def claim(self, _kind: JobKind):
            events.append("claim")
            return [
                Job(
                    id=uid(99),
                    kind=JobKind.SPLIT_CHECK,
                    payload={"node_id": str(node_id)},
                )
            ]

        async def mark(
            self,
            _id: UUID,
            status: JobStatus,
            error: str | None = None,
            retry: bool = True,
        ) -> None:
            assert error is None
            events.append(f"mark:{status.value}:{retry}")

    monkeypatch.setattr(worker_module, "OutboxRepo", RecordingOutbox)
    worker = Worker(app=RecordingApp(), kind=JobKind.SPLIT_CHECK)

    # Act
    processed = await worker.batch()

    # Assert
    assert processed == 1
    assert events == ["claim", "lint", "mark:done:True", "commit"]
