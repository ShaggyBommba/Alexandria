from __future__ import annotations

from asyncio import current_task
from collections.abc import Callable, Hashable
from datetime import datetime
from types import TracebackType

from sqlalchemy.orm import Session, scoped_session

from infrastructure.config import QueueSettings
from infrastructure.repositories.documents import DocumentRepo
from infrastructure.repositories.nodes import NodeRepo
from infrastructure.repositories.outbox import OutboxRepo
from infrastructure.repositories.references import ReferenceRepo


def _session_scope() -> Hashable | None:
    """Return the current asyncio task when one exists, otherwise sync scope."""
    try:
        return current_task()
    except RuntimeError:
        return None


class SqlUnitOfWork:
    """Coordinates repository operations through a task-scoped SQLAlchemy session."""

    def __init__(
        self,
        sessions: Callable[[], Session],
        queue: QueueSettings | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = scoped_session(sessions, scopefunc=_session_scope)
        self.session = self._sessions
        self.nodes = NodeRepo(self.session)
        self.docs = DocumentRepo(self.session)
        self.refs = ReferenceRepo(self.session)
        self.outbox = OutboxRepo(self.session, queue=queue, now=now)

    async def __aenter__(self) -> SqlUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()
        self.close()

    async def commit(self) -> None:
        """Persist all pending repository writes in the current task scope."""
        self.session.commit()

    async def rollback(self) -> None:
        """Discard all pending repository writes in the current task scope."""
        self.session.rollback()

    def close(self) -> None:
        """Close and remove the current task-scoped SQLAlchemy session."""
        self.session.close()
        self._sessions.remove()
