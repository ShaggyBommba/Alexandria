from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.entity import Document


class DocumentRepo:
    """Persists documents attached to semantic leaf nodes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def add(self, doc: Document) -> UUID:
        self._session.add(doc)
        self._session.flush([doc])
        return doc.id

    async def get(self, id: UUID) -> Document | None:
        return self._session.get(Document, id)

    async def leaf(self, id: UUID) -> list[Document]:
        docs = self._session.scalars(
            select(Document)
            .where(Document.leaf_id == id)
            .order_by(Document.created_at.asc(), Document.id.asc())
        ).all()
        return list(docs)

    async def move(self, ids: list[UUID], leaf: UUID) -> None:
        if not ids:
            return

        docs = self._session.scalars(select(Document).where(Document.id.in_(ids))).all()
        for doc in docs:
            doc.leaf_id = leaf

        if docs:
            self._session.flush(docs)

    async def save(self, doc: Document) -> None:
        saved = self._session.merge(doc)
        self._session.flush([saved])

    async def rm(self, id: UUID) -> None:
        doc = self._session.get(Document, id)
        if doc is None:
            return

        self._session.delete(doc)
        self._session.flush()
