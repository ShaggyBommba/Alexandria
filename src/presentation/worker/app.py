from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from application.app import App, get_app
from domain.entity import Job
from domain.values import JobKind, JobStatus
from infrastructure.repositories.outbox import OutboxRepo

logger = logging.getLogger(__name__)


class Worker:
    """Background loop that claims and executes outbox jobs."""

    def __init__(
        self,
        app: App,
        kind: JobKind,
        *,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self.app = app
        self.kind = kind
        self.poll_interval_seconds = poll_interval_seconds
        self.is_running = False

    async def start(self) -> None:
        """Start the worker poll loop."""
        self.is_running = True
        logger.info("Starting outbox worker for kind: %s", self.kind.value)

        while self.is_running:
            try:
                processed_count = await self.batch()
                if processed_count == 0:
                    await asyncio.sleep(self.poll_interval_seconds)
            except Exception as exc:
                logger.error("Unexpected error in worker loop: %s", exc, exc_info=True)
                await asyncio.sleep(self.poll_interval_seconds)

    def stop(self) -> None:
        """Request a graceful stop after the current loop tick."""
        self.is_running = False

    async def batch(self) -> int:
        """Claim and execute a single batch of jobs."""
        with self.app.db.sessions()() as session:
            repo = OutboxRepo(session, self.app.settings.queue)
            jobs = await repo.claim(self.kind)
            if not jobs:
                return 0

            try:
                for job in jobs:
                    try:
                        await self.handle(job)
                        await repo.mark(job.id, JobStatus.DONE)
                    except Exception as error:
                        logger.warning("Job %s failed processing: %s", job.id, error)
                        await repo.mark(job.id, JobStatus.FAILED, str(error))

                session.commit()
                return len(jobs)
            except Exception:
                session.rollback()
                logger.exception("Batch failed; rolled back changes")
                raise

    async def handle(self, job: Job) -> None:
        if job.kind == self.kind:
            node_id = UUID(str(job.payload["node_id"]))
            await self.app.lint(node_id)
            return

        raise ValueError(f"No handler configured for kind: {self.kind.value}")


def main() -> None:
    app: App = get_app()
    worker = Worker(
        app=app,
        kind=JobKind.SPLIT_CHECK,
        poll_interval_seconds=app.settings.app.worker_poll_interval,
    )

    try:
        asyncio.run(worker.start())
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    main()
