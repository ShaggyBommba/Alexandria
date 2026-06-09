from __future__ import annotations

"""Application ports for swappable dependencies."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from domain.entity import Document, Job, Node, Reference
from domain.values import JobKind, JobStatus


@dataclass(frozen=True)
class NodeHit:
    """Node plus query distance."""

    node: Node
    distance: float


@dataclass(frozen=True)
class DocHit:
    """Document plus query distance."""

    doc: Document
    distance: float


@dataclass(frozen=True)
class RefHit:
    """Reference target plus query distance."""

    ref: Reference
    node: Node
    distance: float


@dataclass(frozen=True)
class DocIn:
    """Document input accepted by the ingest boundary."""

    name: str
    body: str
    source_key: str | None = None


@dataclass(frozen=True)
class ChildPlan:
    """One child node proposed by a split adapter."""

    name: str
    description: str
    embedding: list[float]
    docs: list[UUID]


@dataclass(frozen=True)
class SplitPlan:
    """Validated shape expected from a split adapter."""

    children: list[ChildPlan]


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...


@runtime_checkable
class Summarizer(Protocol):
    async def summarize(self, doc: DocIn) -> str: ...


@runtime_checkable
class Splitter(Protocol):
    async def split(self, node: Node, docs: list[Document]) -> SplitPlan: ...


@runtime_checkable
class Ranker(Protocol):
    async def rank(self, query: str, hits: list[DocHit], limit: int) -> list[DocHit]: ...


@runtime_checkable
class NodeRepo(Protocol):
    async def add(self, node: Node) -> UUID: ...
    async def get(self, id: UUID) -> Node | None: ...
    async def root(self) -> Node | None: ...
    async def kids(self, id: UUID) -> list[Node]: ...
    async def leaves(self, limit: int | None = None) -> list[Node]: ...
    async def near(
        self,
        embedding: list[float],
        limit: int,
        parent: UUID | None = None,
        exclude: set[UUID] | None = None,
    ) -> list[NodeHit]: ...
    async def count(self, id: UUID) -> int: ...
    async def save(self, node: Node) -> None: ...
    async def rm(self, id: UUID) -> None: ...


@runtime_checkable
class DocumentRepo(Protocol):
    async def add(self, doc: Document) -> UUID: ...
    async def get(self, id: UUID) -> Document | None: ...
    async def leaf(self, id: UUID) -> list[Document]: ...
    async def near(
        self,
        embedding: list[float],
        limit: int,
        leaves: set[UUID] | None = None,
    ) -> list[DocHit]: ...
    async def move(self, ids: list[UUID], leaf: UUID) -> None: ...
    async def save(self, doc: Document) -> None: ...
    async def rm(self, id: UUID) -> None: ...


@runtime_checkable
class ReferenceRepo(Protocol):
    async def add(self, ref: Reference) -> UUID: ...
    async def get(self, id: UUID) -> Reference | None: ...
    async def out(self, id: UUID, limit: int | None = None) -> list[Reference]: ...
    async def into(self, id: UUID) -> list[Reference]: ...
    async def near(
        self,
        ids: set[UUID],
        embedding: list[float],
        limit: int,
    ) -> list[RefHit]: ...
    async def set(self, id: UUID, refs: list[Reference]) -> None: ...
    async def clear(self, id: UUID) -> None: ...
    async def rm(self, id: UUID) -> None: ...


@runtime_checkable
class OutboxRepo(Protocol):
    async def append(self, job: Job) -> UUID: ...
    async def claim(self, kind: JobKind, limit: int | None = None) -> list[Job]: ...
    async def due(self, kind: JobKind, limit: int | None = None) -> list[Job]: ...
    async def mark(self, id: UUID, status: JobStatus, error: str | None = None) -> None: ...


@runtime_checkable
class UnitOfWork(Protocol):
    nodes: NodeRepo
    docs: DocumentRepo
    refs: ReferenceRepo
    outbox: OutboxRepo

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
