from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from types import TracebackType

from sqlalchemy.orm import Session

from infrastructure.config import QueueSettings
from infrastructure.repositories.documents import DocumentRepo
from infrastructure.repositories.nodes import NodeRepo
from infrastructure.repositories.outbox import OutboxRepo
from infrastructure.repositories.references import ReferenceRepo


class SqlUnitOfWork:
    """Coordinates repository writes inside one SQLAlchemy transaction."""

    def __init__(
        self,
        sessions: Callable[[], Session],
        queue: QueueSettings | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = sessions()
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
        await self.rollback()
        self.close()

    async def commit(self) -> None:
        """Persist all pending repository writes."""
        self.session.commit()

    async def rollback(self) -> None:
        """Discard all pending repository writes."""
        self.session.rollback()

    def close(self) -> None:
        """Close the owned SQLAlchemy session."""
        self.session.close()
