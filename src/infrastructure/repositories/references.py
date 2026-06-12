from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from application.ports import RefHit
from domain.entity import Node, Reference
from infrastructure.exceptions import ReferenceSourceMismatch
from infrastructure.utils.vector import cosine_distance


class ReferenceRepo:
    """Persists directed semantic references between nodes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def add(self, ref: Reference) -> UUID:
        self._session.add(ref)
        self._session.flush([ref])
        return ref.id

    async def get(self, id: UUID) -> Reference | None:
        return self._session.get(Reference, id)

    async def out(self, id: UUID, limit: int | None = None) -> list[Reference]:
        stmt = (
            select(Reference)
            .where(Reference.from_node_id == id)
            .order_by(Reference.rank.asc(), Reference.id.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        refs = self._session.scalars(stmt).all()
        return list(refs)

    async def into(self, id: UUID) -> list[Reference]:
        refs = self._session.scalars(
            select(Reference)
            .where(Reference.to_node_id == id)
            .order_by(Reference.rank.asc(), Reference.id.asc())
        ).all()
        return list(refs)

    async def near(
        self,
        ids: set[UUID],
        embedding: list[float],
        limit: int,
    ) -> list[RefHit]:
        if not ids or limit <= 0:
            return []

        if self.vector_sql_enabled():
            qdist = Node.embedding.cosine_distance(embedding).label("qdist")
            rows = self._session.execute(
                select(Reference, Node, qdist)
                .join(Node, Reference.to_node_id == Node.id)
                .where(
                    Reference.from_node_id.in_(sorted(ids)),
                    Node.kind == "leaf",
                    Node.status == "active",
                )
                .order_by(qdist.asc(), Reference.rank.asc(), Reference.id.asc())
                .limit(limit)
            ).all()
            return [
                RefHit(ref=ref, node=node, distance=float(qdist))
                for ref, node, qdist in rows
            ]

        rows = self._session.execute(
            select(Reference, Node)
            .join(Node, Reference.to_node_id == Node.id)
            .where(
                Reference.from_node_id.in_(sorted(ids)),
                Node.kind == "leaf",
                Node.status == "active",
            )
            .order_by(Reference.rank.asc(), Reference.id.asc())
        ).all()
        hits = [
            RefHit(
                ref=ref,
                node=node,
                distance=cosine_distance(embedding, list(node.embedding)),
            )
            for ref, node in rows
        ]
        hits.sort(key=lambda hit: (hit.distance, hit.ref.rank, str(hit.ref.id)))
        return hits[:limit]

    def vector_sql_enabled(self) -> bool:
        """Return whether this session can execute pgvector distance SQL."""
        return self._session.get_bind().dialect.name == "postgresql"

    async def set(self, id: UUID, refs: list[Reference]) -> None:
        for ref in refs:
            if ref.from_node_id != id:
                raise ReferenceSourceMismatch(
                    f"reference {ref.id} belongs to {ref.from_node_id}, not {id}",
                )

        with self._session.no_autoflush:
            self._session.execute(delete(Reference).where(Reference.from_node_id == id))
            self._session.add_all(refs)
        self._session.flush()

    async def clear(self, id: UUID) -> None:
        self._session.execute(delete(Reference).where(Reference.from_node_id == id))
        self._session.flush()

    async def rm(self, id: UUID) -> None:
        ref = self._session.get(Reference, id)
        if ref is None:
            return

        self._session.delete(ref)
        self._session.flush()
