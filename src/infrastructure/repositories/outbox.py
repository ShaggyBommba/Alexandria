from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from domain.entity import Job
from domain.values import JobKind, JobStatus
from infrastructure.config import QueueSettings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OutboxRepo:
    """Manages outbox persistency using a Shared Kernel architecture pattern."""

    def __init__(
        self,
        session: Session,
        queue: QueueSettings | None = None,
        now: Callable[[], datetime] | None = None,
        queue_settings: QueueSettings | None = None,
    ) -> None:
        self._session = session
        queue_config = queue if queue is not None else queue_settings
        if queue_config is None:
            queue_config = QueueSettings()
        self._queue_settings = queue_config
        self._now = now or utcnow

    async def append(self, job: Job) -> UUID:
        """Insert a new outbox job using key-based idempotency."""
        now = self._now()
        target_available_at = job.available_at or now

        if job.key is not None:
            existing_job = self._session.scalar(
                select(Job).where(Job.key == job.key),
            )
            if existing_job is not None:
                if existing_job.status in {
                    JobStatus.PENDING.value,
                    JobStatus.RUNNING.value,
                }:
                    return existing_job.id

                existing_job.kind = job.kind
                existing_job.payload = job.payload
                existing_job.status = JobStatus.PENDING.value
                existing_job.attempts = 0
                existing_job.max_attempts = job.max_attempts
                existing_job.last_error = None
                existing_job.available_at = target_available_at
                existing_job.locked_at = None
                existing_job.done_at = None

                self._session.flush([existing_job])
                return existing_job.id

        if not job.available_at:
            job.available_at = target_available_at

        self._session.add(job)
        self._session.flush([job])
        return job.id

    async def due(self, kind: JobKind, limit: int | None = None) -> list[Job]:
        """Return ready pending jobs for a kind without locking them."""
        now = self._now()
        batch_size = limit if limit is not None else self._queue_settings.batch_size

        jobs = self._session.scalars(
            select(Job)
            .where(
                Job.kind == kind.value,
                Job.status == JobStatus.PENDING.value,
                or_(
                    Job.available_at.is_(None),
                    Job.available_at <= now,
                ),
            )
            .order_by(
                Job.available_at.asc().nullsfirst(),
                Job.created_at.asc(),
                Job.id.asc(),
            )
            .limit(batch_size)
        ).all()

        return list(jobs)

    async def claim(self, kind: JobKind, limit: int | None = None) -> list[Job]:
        now = self._now()
        batch_size = limit if limit is not None else self._queue_settings.batch_size

        jobs = self._session.scalars(
            select(Job)
            .where(
                Job.kind == kind.value,
                Job.status == JobStatus.PENDING.value,
                or_(
                    Job.available_at.is_(None),
                    Job.available_at <= now,
                ),
            )
            .order_by(
                Job.available_at.asc().nullsfirst(),
                Job.created_at.asc(),
                Job.id.asc(),
            )
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()

        for job in jobs:
            job.status = JobStatus.RUNNING.value
            job.locked_at = now
            job.attempts += 1

        if jobs:
            self._session.flush(jobs)

        return list(jobs)

    async def mark(
        self,
        id: UUID,
        status: JobStatus,
        error: str | None = None,
        retry: bool = True,
    ) -> None:
        """Atomically transitions a job's lifecycle status and handles side effects."""
        job = self._session.get(Job, id)
        if job is None:
            return

        now = self._now()
        job.status = status.value
        job.locked_at = None
        job.last_error = error if error else None

        match status:
            case JobStatus.DONE:
                job.done_at = now

            case JobStatus.FAILED:
                job.done_at = None
                if retry and job.attempts < job.max_attempts:
                    job.status = JobStatus.PENDING.value
                    job.available_at = now
                else:
                    job.status = JobStatus.FAILED.value

            case JobStatus.PENDING:
                job.done_at = None
                job.available_at = now

        self._session.flush([job])
