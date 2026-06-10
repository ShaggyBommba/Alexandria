from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from application.ports import ReferenceRepo as ReferencePort
from domain.entity import Base, Node, Reference, VECTOR_DIMENSIONS
from infrastructure.exceptions import ReferenceSourceMismatch
from infrastructure.repositories.references import ReferenceRepo


@pytest.fixture
def ref_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [Node.__table__, Reference.__table__]
    Base.metadata.create_all(engine, tables=tables)
    try:
        with Session(engine) as session:
            yield session
    finally:
        Base.metadata.drop_all(engine, tables=tables)
        engine.dispose()


def uid(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012x}")


def vector(*values: float) -> list[float]:
    embedding = [0.0] * VECTOR_DIMENSIONS
    for index, value in enumerate(values):
        embedding[index] = value
    return embedding


def node(
    value: int,
    *,
    embedding: list[float] | None = None,
    kind: str = "leaf",
    status: str = "active",
) -> Node:
    return Node(
        id=uid(value),
        name=f"Node {value}",
        description=f"Description {value}",
        embedding=embedding or vector(1.0),
        kind=kind,
        status=status,
    )


def reference(
    value: int,
    source: Node,
    target: Node,
    *,
    rank: int = 0,
    distance: float = 0.1,
    method: str = "embedding",
) -> Reference:
    return Reference(
        id=uid(value),
        from_node=source,
        to_node=target,
        distance=distance,
        rank=rank,
        method=method,
    )


def repo(session: Session) -> ReferenceRepo:
    return ReferenceRepo(session)


class FakeResult:
    def __init__(self, rows: list[tuple[Reference, Node, float]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[Reference, Node, float]]:
        return self.rows


class FakeSession:
    def __init__(self, rows: list[tuple[Reference, Node, float]]) -> None:
        self.rows = rows
        self.statement = None

    def execute(self, statement):
        self.statement = statement
        return FakeResult(self.rows)


def test_reference_repo_satisfies_port(ref_session) -> None:
    refs = repo(ref_session)

    assert isinstance(refs, ReferencePort)


@pytest.mark.asyncio
async def test_add_persists_reference_and_get_returns_it(ref_session) -> None:
    refs = repo(ref_session)
    source = node(1)
    target = node(2)
    ref_session.add_all([source, target])
    ref = reference(10, source, target, rank=2, distance=0.34)

    id = await refs.add(ref)

    saved = await refs.get(id)
    assert id == uid(10)
    assert saved is ref
    assert saved.from_node_id == source.id
    assert saved.to_node_id == target.id
    assert saved.rank == 2
    assert saved.distance == pytest.approx(0.34)


@pytest.mark.asyncio
async def test_out_returns_ranked_outgoing_references_with_limit(ref_session) -> None:
    refs = repo(ref_session)
    source = node(1)
    first = node(2)
    second = node(3)
    unrelated = node(4)
    high = reference(10, source, second, rank=3)
    low = reference(11, source, first, rank=1)
    other = reference(12, unrelated, first, rank=0)
    ref_session.add_all([source, first, second, unrelated, high, low, other])
    ref_session.flush()

    result = await refs.out(source.id, limit=1)

    assert [item.id for item in result] == [low.id]


@pytest.mark.asyncio
async def test_into_returns_ranked_incoming_references(ref_session) -> None:
    refs = repo(ref_session)
    target = node(1)
    first = node(2)
    second = node(3)
    unrelated = node(4)
    high = reference(10, second, target, rank=2)
    low = reference(11, first, target, rank=0)
    other = reference(12, first, unrelated, rank=0)
    ref_session.add_all([target, first, second, unrelated, high, low, other])
    ref_session.flush()

    result = await refs.into(target.id)

    assert [item.id for item in result] == [low.id, high.id]


@pytest.mark.asyncio
async def test_set_replaces_outgoing_references_for_source(ref_session) -> None:
    refs = repo(ref_session)
    source = node(1)
    old_target = node(2)
    new_target = node(3)
    other_source = node(4)
    existing = reference(10, source, old_target, rank=0)
    other = reference(12, other_source, old_target, rank=0)
    ref_session.add_all([source, old_target, new_target, other_source, existing, other])
    ref_session.flush()
    replacement = Reference(
        id=uid(11),
        from_node_id=source.id,
        to_node_id=new_target.id,
        distance=0.1,
        rank=0,
    )

    await refs.set(source.id, [replacement])

    assert [item.id for item in await refs.out(source.id)] == [replacement.id]
    assert [item.id for item in await refs.out(other_source.id)] == [other.id]
    assert await refs.get(existing.id) is None


@pytest.mark.asyncio
async def test_set_rejects_refs_from_another_source_without_deleting_existing(
    ref_session,
) -> None:
    refs = repo(ref_session)
    source = node(1)
    target = node(2)
    other_source = node(3)
    existing = reference(10, source, target, rank=0)
    ref_session.add_all([source, target, other_source, existing])
    ref_session.flush()
    bad = Reference(
        id=uid(11),
        from_node_id=other_source.id,
        to_node_id=target.id,
        distance=0.1,
        rank=0,
    )

    with pytest.raises(ReferenceSourceMismatch):
        await refs.set(source.id, [bad])

    assert [item.id for item in await refs.out(source.id)] == [existing.id]


@pytest.mark.asyncio
async def test_clear_and_rm_delete_references_and_ignore_missing_rows(
    ref_session,
) -> None:
    refs = repo(ref_session)
    source = node(1)
    first = node(2)
    second = node(3)
    other_source = node(4)
    outgoing = reference(10, source, first, rank=0)
    removed = reference(11, other_source, second, rank=0)
    kept = reference(12, other_source, first, rank=1)
    ref_session.add_all([source, first, second, other_source, outgoing, removed, kept])
    ref_session.flush()

    await refs.clear(source.id)
    await refs.rm(removed.id)
    await refs.rm(uid(99))

    assert await refs.out(source.id) == []
    assert await refs.get(removed.id) is None
    assert [item.id for item in await refs.out(other_source.id)] == [kept.id]


@pytest.mark.asyncio
async def test_near_returns_referenced_nodes_ranked_by_query_distance() -> None:
    target = node(3, embedding=vector(1.0, 0.0))
    ref = Reference(
        id=uid(10),
        from_node_id=uid(1),
        to_node_id=target.id,
        distance=0.12,
        rank=1,
    )
    session = FakeSession([(ref, target, 0.04)])
    refs = ReferenceRepo(session)

    result = await refs.near({uid(2), uid(1)}, vector(1.0, 0.0), limit=3)

    assert result[0].ref is ref
    assert result[0].node is target
    assert result[0].distance == pytest.approx(0.04)
    assert session.statement is not None
    compiled = session.statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "nodes.embedding <=> %(embedding_1)s AS distance" in sql
    assert 'JOIN nodes ON "references".to_node_id = nodes.id' in sql
    assert '"references".from_node_id IN' in sql
    assert "nodes.kind = %(kind_1)s" in sql
    assert "nodes.status = %(status_1)s" in sql
    assert 'ORDER BY distance ASC, "references".rank ASC, "references".id ASC' in sql
    assert compiled.params["from_node_id_1"] == [uid(1), uid(2)]
    assert compiled.params["kind_1"] == "leaf"
    assert compiled.params["status_1"] == "active"
    assert compiled.params["param_1"] == 3


@pytest.mark.asyncio
async def test_near_ignores_empty_source_sets() -> None:
    session = FakeSession([])
    refs = ReferenceRepo(session)

    result = await refs.near(set(), vector(1.0, 0.0), limit=3)

    assert result == []
    assert session.statement is None
