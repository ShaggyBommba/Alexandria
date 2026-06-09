from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from domain.entity import Job
from infrastructure.repositories.db import Base


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Job.__table__])
    try:
        with Session(engine) as session:
            yield session
    finally:
        Base.metadata.drop_all(engine, tables=[Job.__table__])
        engine.dispose()
