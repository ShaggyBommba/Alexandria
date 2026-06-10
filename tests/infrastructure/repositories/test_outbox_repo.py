from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from application.ports import OutboxRepo as OutboxPort
from domain.entity import Job
from domain.values import JobKind, JobStatus
from infrastructure.config import QueueSettings
from infrastructure.repositories.outbox import OutboxRepo


def repo(db_session, now, **settings) -> OutboxRepo:
    queue = QueueSettings(**settings)
    return OutboxRepo(db_session, queue=queue, now=lambda: now)


def row(db_session, id: UUID) -> Job:
    result = db_session.get(Job, id)
    assert result is not None
    return result


def as_value(value: JobKind | JobStatus | str) -> str:
    return value.value if isinstance(value, (JobKind, JobStatus)) else value


def test_outbox_repo_satisfies_ports(db_session, now) -> None:
    outbox = repo(db_session, now)

    assert isinstance(outbox, OutboxPort)


@pytest.mark.asyncio
async def test_append_inserts_outbox_row(db_session, now) -> None:
    outbox = repo(db_session, now, max_attempts=7)
    job = Job(
        kind=JobKind.EMAIL_SEND,
        payload={"to": "user@example.com"},
        key=UUID("00000000-0000-0000-0000-000000000001"),
        max_attempts=7,
    )

    id = await outbox.append(job)

    saved = row(db_session, id)
    assert saved.kind == as_value(JobKind.EMAIL_SEND)
    assert saved.payload == {"to": "user@example.com"}
    assert saved.key == UUID("00000000-0000-0000-0000-000000000001")
    assert saved.status == as_value(JobStatus.PENDING)
    assert saved.attempts == 0
    assert saved.max_attempts == 7
    assert saved.available_at == now


@pytest.mark.asyncio
async def test_append_returns_existing_pending_key_without_rewriting_payload(
    db_session,
    now,
) -> None:
    outbox = repo(db_session, now)
    key = UUID("00000000-0000-0000-0000-000000000001")
    first = await outbox.append(
        Job(kind=JobKind.EMAIL_SEND, payload={"to": "a@example.com"}, key=key),
    )

    second = await outbox.append(
        Job(kind=JobKind.EMAIL_SEND, payload={"to": "b@example.com"}, key=key),
    )

    saved = row(db_session, first)
    assert second == first
    assert saved.payload == {"to": "a@example.com"}


@pytest.mark.asyncio
async def test_append_revives_finished_key(db_session, now) -> None:
    outbox = repo(db_session, now, max_attempts=4)
    key = UUID("00000000-0000-0000-0000-000000000001")
    id = await outbox.append(
        Job(kind=JobKind.EMAIL_SEND, payload={"to": "a@example.com"}, key=key),
    )
    saved = row(db_session, id)
    saved.status = "done"
    saved.done_at = now + timedelta(minutes=1)
    saved.attempts = 3
    saved.last_error = "old failure"

    revived = await outbox.append(
        Job(
            kind=JobKind.EMAIL_SEND,
            payload={"to": "b@example.com"},
            key=key,
            max_attempts=4,
        ),
    )

    result = row(db_session, id)
    assert revived == id
    assert result.payload == {"to": "b@example.com"}
    assert result.status == as_value(JobStatus.PENDING)
    assert result.attempts == 0
    assert result.max_attempts == 4
    assert result.locked_at is None
    assert result.done_at is None
    assert result.last_error is None
    assert result.available_at == now


@pytest.mark.asyncio
async def test_append_inserts_idempotent_split_check_job(db_session, now) -> None:
    outbox = repo(db_session, now)
    node_id = UUID("00000000-0000-0000-0000-000000000001")
    job = Job(
        kind=JobKind.SPLIT_CHECK,
        payload={"node_id": str(node_id)},
        key=node_id,
    )

    first = await outbox.append(job)
    second = await outbox.append(job)

    saved = row(db_session, first)
    assert second == first
    assert saved.kind == as_value(JobKind.SPLIT_CHECK)
    assert saved.payload == {"node_id": str(node_id)}
    assert saved.key == node_id


@pytest.mark.asyncio
async def test_due_returns_ready_pending_rows_by_kind(db_session, now) -> None:
    outbox = repo(db_session, now, batch_size=1)
    due = await outbox.append(Job(kind=JobKind.EMAIL_SEND, payload={"n": 1}))
    later = await outbox.append(Job(kind=JobKind.EMAIL_SEND, payload={"n": 2}))
    other = await outbox.append(Job(kind=JobKind.WEBHOOK_SEND, payload={"n": 3}))
    row(db_session, later).available_at = now + timedelta(minutes=5)
    row(db_session, other).available_at = now

    jobs = await outbox.due(JobKind.EMAIL_SEND)

    assert [job.id for job in jobs] == [due]
    assert jobs[0].kind == as_value(JobKind.EMAIL_SEND)


@pytest.mark.asyncio
async def test_claim_locks_due_rows(db_session, now) -> None:
    outbox = repo(db_session, now)
    id = await outbox.append(Job(kind=JobKind.EMAIL_SEND, payload={"n": 1}))

    jobs = await outbox.claim(JobKind.EMAIL_SEND)

    assert [job.id for job in jobs] == [id]
    assert jobs[0].status == as_value(JobStatus.RUNNING)
    assert jobs[0].attempts == 1
    saved = row(db_session, id)
    assert saved.status == as_value(JobStatus.RUNNING)
    assert saved.locked_at == now
    assert saved.attempts == 1


@pytest.mark.asyncio
async def test_mark_pending_makes_claimed_job_pending_again(db_session, now) -> None:
    outbox = repo(db_session, now)
    id = await outbox.append(Job(kind=JobKind.EMAIL_SEND, payload={"n": 1}))
    await outbox.claim(JobKind.EMAIL_SEND)

    await outbox.mark(id, JobStatus.PENDING)

    saved = row(db_session, id)
    assert saved.status == as_value(JobStatus.PENDING)
    assert saved.locked_at is None
    assert saved.done_at is None
    assert saved.available_at == now


@pytest.mark.asyncio
async def test_claim_claims_split_check_rows_as_domain_jobs(db_session, now) -> None:
    outbox = repo(db_session, now)
    node_id = UUID("00000000-0000-0000-0000-000000000001")
    id = await outbox.append(
        Job(kind=JobKind.SPLIT_CHECK, payload={"node_id": str(node_id)}),
    )

    jobs = await outbox.claim(JobKind.SPLIT_CHECK)

    assert [job.id for job in jobs] == [id]
    assert jobs[0].kind == as_value(JobKind.SPLIT_CHECK)
    assert jobs[0].payload == {"node_id": str(node_id)}
    assert jobs[0].status == as_value(JobStatus.RUNNING)
    assert row(db_session, id).status == as_value(JobStatus.RUNNING)


@pytest.mark.asyncio
async def test_mark_done_marks_job_complete_and_ignores_missing_rows(
    db_session, now
) -> None:
    outbox = repo(db_session, now)
    id = await outbox.append(Job(kind=JobKind.EMAIL_SEND, payload={"n": 1}))
    await outbox.claim(JobKind.EMAIL_SEND)

    await outbox.mark(id, JobStatus.DONE)
    await outbox.mark(uuid4(), JobStatus.DONE)

    saved = row(db_session, id)
    assert saved.status == as_value(JobStatus.DONE)
    assert saved.locked_at is None
    assert saved.last_error is None
    assert saved.done_at == now


@pytest.mark.asyncio
async def test_mark_failed_requeues_until_attempts_are_exhausted(
    db_session, now
) -> None:
    outbox = repo(db_session, now, max_attempts=2)
    retryable = await outbox.append(
        Job(kind=JobKind.EMAIL_SEND, payload={"n": 1}, max_attempts=2),
    )
    exhausted = await outbox.append(
        Job(kind=JobKind.EMAIL_SEND, payload={"n": 2}, max_attempts=1),
    )
    row(db_session, exhausted).max_attempts = 1
    await outbox.claim(JobKind.EMAIL_SEND)

    await outbox.mark(retryable, JobStatus.FAILED, "temporary failure")
    await outbox.mark(exhausted, JobStatus.FAILED, "permanent failure")
    await outbox.mark(uuid4(), JobStatus.FAILED, "missing")

    retryable_row = row(db_session, retryable)
    exhausted_row = row(db_session, exhausted)
    assert retryable_row.status == as_value(JobStatus.PENDING)
    assert retryable_row.last_error == "temporary failure"
    assert retryable_row.locked_at is None
    assert retryable_row.done_at is None
    assert retryable_row.available_at == now
    assert exhausted_row.status == as_value(JobStatus.FAILED)
    assert exhausted_row.last_error == "permanent failure"
    assert exhausted_row.locked_at is None
