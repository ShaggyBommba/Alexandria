from __future__ import annotations

from logging import getLogger
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from application.ports import NodeHit
from domain.entity import Document, Node
from infrastructure.utils.vector import cosine_distance

logging = getLogger(__name__)


class NodeRepo:
    """Persists and queries semantic tree nodes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def add(self, node: Node) -> UUID:
        self._session.add(node)
        self._session.flush([node])
        return node.id

    async def get(self, id: UUID) -> Node | None:
        return self._session.get(Node, id)

    async def root(self) -> Node | None:
        return self._session.scalar(
            select(Node)
            .where(
                Node.parent_id.is_(None),
                Node.status == "active",
            )
            .order_by(Node.created_at.asc(), Node.id.asc())
            .limit(1)
        )

    async def kids(self, id: UUID) -> list[Node]:
        nodes = self._session.scalars(
            select(Node)
            .where(Node.parent_id == id)
            .order_by(Node.created_at.asc(), Node.id.asc())
        ).all()
        return list(nodes)

    async def leaves(self, limit: int | None = None) -> list[Node]:
        stmt = (
            select(Node)
            .where(
                Node.kind == "leaf",
                Node.status == "active",
            )
            .order_by(Node.created_at.asc(), Node.id.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)

        nodes = self._session.scalars(stmt).all()
        return list(nodes)

    async def near(
        self,
        embedding: list[float],
        limit: int,
        parent: UUID | None = None,
        exclude: set[UUID] | None = None,
    ) -> list[NodeHit]:
        if limit <= 0:
            return []

        filters = [Node.status == "active"]
        if parent is not None:
            filters.append(Node.parent_id == parent)
        if exclude:
            filters.append(Node.id.not_in(exclude))

        if self._session.get_bind().dialect.name == "postgresql":
            qdist = Node.embedding.cosine_distance(embedding).label("qdist")
            rows = self._session.execute(
                select(Node, qdist)
                .where(*filters)
                .order_by(qdist.asc(), Node.id.asc())
                .limit(limit)
            ).all()
            return [NodeHit(node=node, distance=float(qdist)) for node, qdist in rows]

        nodes = self._session.scalars(
            select(Node).where(*filters).order_by(Node.id.asc())
        ).all()
        hits = [
            NodeHit(node=node, distance=cosine_distance(embedding, list(node.embedding)))
            for node in nodes
        ]
        hits.sort(key=lambda hit: (hit.distance, str(hit.node.id)))
        return hits[:limit]

    async def count(self, id: UUID) -> int:
        count = self._session.scalar(
            select(func.count()).select_from(Document).where(Document.leaf_id == id)
        )
        return int(count or 0)

    async def save(self, node: Node) -> None:
        saved = self._session.merge(node)
        self._session.flush([saved])

    async def rm(self, id: UUID) -> None:
        node = self._session.get(Node, id)
        if node is None:
            return

        self._session.delete(node)
        self._session.flush()
