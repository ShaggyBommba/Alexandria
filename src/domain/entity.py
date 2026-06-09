from __future__ import annotations
from datetime import datetime
from typing import Any
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, Uuid, UniqueConstraint, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

VECTOR_DIMENSIONS = 1536 

class Base(DeclarativeBase):
    """Infrastructure foundation that our Shared Kernel models inherit from."""

    def __init__(self, **values: Any) -> None:
        """Assign mapped values with the same shape as SQLAlchemy's constructor."""
        for name, value in values.items():
            if not hasattr(type(self), name):
                raise TypeError(f"{type(self).__name__} got unexpected field: {name}")
            setattr(self, name, value)


class Node(Base):
    """Semantic tree node used to route documents through the dynamic index."""
    __tablename__ = "nodes"

    __table_args__ = (
        CheckConstraint("kind IN ('branch', 'leaf')", name="nodes_kind_check"),
        CheckConstraint("status IN ('active', 'splitting', 'retired')", name="nodes_status_check"),
        CheckConstraint("doc_count >= 0", name="nodes_doc_count_check"),
        CheckConstraint("version >= 1", name="nodes_version_check"),
        Index("ix_nodes_parent_kind", "parent_id", "kind"),
        Index("ix_nodes_status", "status"),
        # CRITICAL: HNSW Index for fast vector similarity search during tree traversal
        Index(
            "ix_nodes_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"}
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), nullable=True)

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(VECTOR_DIMENSIONS), nullable=False)

    kind: Mapped[str] = mapped_column(String, nullable=False, default="leaf")
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    parent: Mapped[Node | None] = relationship(
        "Node",
        remote_side=[id],
        back_populates="children",
    )
    children: Mapped[list[Node]] = relationship(
        "Node",
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list[Document]] = relationship(
        "Document",
        back_populates="leaf",
        cascade="all, delete-orphan",
    )
    references: Mapped[list[Reference]] = relationship(
        "Reference",
        foreign_keys="[Reference.from_node_id]",
        back_populates="from_node",
        cascade="all, delete-orphan",
    )
    referenced_by: Mapped[list[Reference]] = relationship(
        "Reference",
        foreign_keys="[Reference.to_node_id]",
        back_populates="to_node",
        cascade="all, delete-orphan",
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __init__(self, **values: Any) -> None:
        values.setdefault("id", uuid.uuid4())
        values.setdefault("kind", "leaf")
        values.setdefault("status", "active")
        values.setdefault("doc_count", 0)
        values.setdefault("version", 1)
        super().__init__(**values)

class Document(Base):
    """Stored document attached to one leaf node in the dynamic index."""
    __tablename__ = "documents"

    __table_args__ = (
        Index("ix_documents_leaf_id", "leaf_id"),
        Index("ix_documents_source_key", "source_key"),
        # Index for agent's local search after navigating the node highway
        Index(
            "ix_documents_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"}
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    leaf_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    source_key: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)

    name: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(VECTOR_DIMENSIONS), nullable=False)

    leaf: Mapped[Node] = relationship(
        "Node",
        back_populates="documents",
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __init__(self, **values: Any) -> None:
        values.setdefault("id", uuid.uuid4())
        super().__init__(**values)

class Reference(Base):
    """Directed semantic reference from one node to another."""
    __tablename__ = "references"

    __table_args__ = (
        CheckConstraint("from_node_id != to_node_id", name="references_no_self_ref_check"),
        CheckConstraint("rank >= 0", name="references_rank_check"),
        UniqueConstraint("from_node_id", "to_node_id", name="uq_references_pair"),
        Index("ix_references_from_rank", "from_node_id", "rank"),
        Index("ix_references_to_node", "to_node_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    to_node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)

    distance: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    method: Mapped[str] = mapped_column(String, nullable=False, default="embedding")

    from_node: Mapped["Node"] = relationship(
        "Node",
        foreign_keys=[from_node_id],
        back_populates="references",
    )
    to_node: Mapped["Node"] = relationship(
        "Node",
        foreign_keys=[to_node_id],
        back_populates="referenced_by",
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __init__(self, **values: Any) -> None:
        values.setdefault("id", uuid.uuid4())
        values.setdefault("rank", 0)
        values.setdefault("method", "embedding")
        super().__init__(**values)

class Job(Base):
    """The Shared Kernel: This is both your Domain Entity and your DB Model."""
    __tablename__ = "outbox"

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed')",
            name="outbox_status_check",
        ),
        Index("ix_outbox_kind_status_available_at", "kind", "status", "available_at"),
        Index("ix_outbox_status_locked_at", "status", "locked_at"),
    )

    # Identifiers
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, unique=True)
    
    # Business Payload (Uses native python Enums directly supported by SQLAlchemy mapping)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    
    # State Machine Variables
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Lifecycles
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Audit Logs
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
        if self.id is None:
            self.id = uuid.uuid4()
        if isinstance(self.key, str):
            self.key = uuid.UUID(self.key)
        if self.payload is None:
            self.payload = {}
        if self.status is None:
            self.status = "pending"
        if self.attempts is None:
            self.attempts = 0
        if self.max_attempts is None:
            self.max_attempts = 3
