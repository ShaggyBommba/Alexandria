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
