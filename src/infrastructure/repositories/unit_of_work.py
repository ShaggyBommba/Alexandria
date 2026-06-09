from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
from datetime import datetime
from types import TracebackType

from sqlalchemy.orm import Session

from infrastructure.config import QueueSettings
from infrastructure.repositories.documents import DocumentRepo
from infrastructure.repositories.nodes import NodeRepo
from infrastructure.repositories.outbox import OutboxRepo
from infrastructure.repositories.references import ReferenceRepo


class _SqlUnitOfWorkScope:
    """Owns one SQLAlchemy session and its repository adapters."""

    def __init__(
        self,
        session: Session,
        queue: QueueSettings | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.nodes = NodeRepo(self.session)
        self.docs = DocumentRepo(self.session)
        self.refs = ReferenceRepo(self.session)
        self.outbox = OutboxRepo(self.session, queue=queue, now=now)

    async def __aenter__(self) -> _SqlUnitOfWorkScope:
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
        """Persist all pending repository writes."""
        self.session.commit()

    async def rollback(self) -> None:
        """Discard all pending repository writes."""
        self.session.rollback()

    def close(self) -> None:
        """Close the owned SQLAlchemy session."""
        self.session.close()


class SqlUnitOfWork:
    """Creates SQLAlchemy unit-of-work scopes from a session factory."""

    def __init__(
        self,
        sessions: Callable[[], Session],
        queue: QueueSettings | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._queue = queue
        self._now = now
        self._scope: _SqlUnitOfWorkScope | None = None
        self._active_scope: ContextVar[_SqlUnitOfWorkScope | None] = ContextVar(
            "sql_unit_of_work_scope",
            default=None,
        )
        self._active_tokens: dict[int, Token[_SqlUnitOfWorkScope | None]] = {}

    def _new_scope(self) -> _SqlUnitOfWorkScope:
        return _SqlUnitOfWorkScope(self._sessions(), queue=self._queue, now=self._now)

    def _current_scope(self) -> _SqlUnitOfWorkScope:
        if self._scope is None:
            self._scope = self._new_scope()
        return self._scope

    @property
    def session(self) -> Session:
        return self._current_scope().session

    @property
    def nodes(self) -> NodeRepo:
        return self._current_scope().nodes

    @property
    def docs(self) -> DocumentRepo:
        return self._current_scope().docs

    @property
    def refs(self) -> ReferenceRepo:
        return self._current_scope().refs

    @property
    def outbox(self) -> OutboxRepo:
        return self._current_scope().outbox

    async def __aenter__(self) -> _SqlUnitOfWorkScope:
        scope = self._new_scope()
        token = self._active_scope.set(scope)
        self._active_tokens[id(scope)] = token
        return await scope.__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        scope = self._active_scope.get()
        if scope is None:
            return

        token = self._active_tokens.pop(id(scope))
        try:
            await scope.__aexit__(exc_type, exc, traceback)
        finally:
            self._active_scope.reset(token)

    async def commit(self) -> None:
        """Persist all pending repository writes in the direct-use scope."""
        await self._current_scope().commit()

    async def rollback(self) -> None:
        """Discard all pending repository writes in the direct-use scope."""
        await self._current_scope().rollback()

    def close(self) -> None:
        """Close the direct-use SQLAlchemy session, if one was opened."""
        if self._scope is None:
            return

        self._scope.close()
        self._scope = None
