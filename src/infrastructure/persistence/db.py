from __future__ import annotations

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from infrastructure.config import SQLSettings
from domain.entity import Base


class Db:
    """SQLAlchemy database factory for engines, sessions, and schema setup."""

    def __init__(self, settings: SQLSettings) -> None:
        """Keep database settings and lazily create SQLAlchemy objects."""
        self.settings = settings
        self._engine: Engine | None = None
        self._sessions: sessionmaker[Session] | None = None

    def engine(self) -> Engine:
        """Return the shared SQLAlchemy engine."""
        if self._engine is None:
            self._engine = create_engine(self.settings.dsn)
        return self._engine

    def sessions(self) -> sessionmaker[Session]:
        """Return the session factory used by repositories and units of work."""
        if self._sessions is None:
            self._sessions = sessionmaker(bind=self.engine())
        return self._sessions

    def session(self) -> Session:
        """Open one database session."""
        return self.sessions()()

    def extensions(self) -> None:
        """Ensure database extensions needed by row models are available."""
        with self.engine().begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    def create_all(self) -> None:
        """Create all known database tables."""
        self.extensions()
        Base.metadata.create_all(self.engine())

    def close(self) -> None:
        """Dispose the database engine when this factory is no longer needed."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._sessions = None

    def drop_all(self) -> None:
        """Drop all known database tables."""
        Base.metadata.drop_all(self.engine())
