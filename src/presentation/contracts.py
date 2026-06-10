"""Shared contracts for public presentation boundaries."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator

from application.ports import DocHit, DocIn
from domain.exceptions import BaseError


class IngestRequest(BaseModel):
    """Transport input for ingesting one document."""

    name: str
    body: str
    source_key: str | None = None

    @field_validator("name")
    @classmethod
    def required_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("value must not be blank")
        return text

    @field_validator("body")
    @classmethod
    def required_body(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    @field_validator("source_key")
    @classmethod
    def optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    def doc(self) -> DocIn:
        """Convert transport input to the application ingest shape."""
        return DocIn(name=self.name, body=self.body, source_key=self.source_key)


class IngestResponse(BaseModel):
    """Transport response for ingesting one document."""

    id: UUID


class RetrieveRequest(BaseModel):
    """Transport input for retrieving documents."""

    query: str
    limit: int = Field(default=10, ge=1)

    @field_validator("query")
    @classmethod
    def required_query(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("query must not be blank")
        return text


class DocumentHitResponse(BaseModel):
    """Transport-safe document hit returned to public clients."""

    id: UUID
    leaf_id: UUID
    source_key: str | None
    name: str
    summary: str
    body: str
    score: float
    distance: float | None
    bm25: float | None

    @classmethod
    def from_hit(cls, hit: DocHit) -> DocumentHitResponse:
        """Build a public hit shape without ORM internals or embeddings."""
        doc = hit.doc
        return cls(
            id=doc.id,
            leaf_id=doc.leaf_id,
            source_key=doc.source_key,
            name=doc.name,
            summary=doc.summary,
            body=doc.body,
            score=hit.score,
            distance=hit.distance,
            bm25=hit.bm25,
        )


class RetrieveResponse(BaseModel):
    """Transport response for document retrieval."""

    hits: list[DocumentHitResponse]

    @classmethod
    def from_hits(cls, hits: list[DocHit]) -> RetrieveResponse:
        """Build a public retrieval response from application hits."""
        return cls(hits=[DocumentHitResponse.from_hit(hit) for hit in hits])


def error_payload(exc: BaseError) -> dict[str, dict[str, str]]:
    """Return the transport-neutral shape for expected workflow errors."""
    return {"error": {"code": exc.code, "message": str(exc)}}


def validation_message(exc: ValidationError) -> str:
    """Return a compact validation message for text transports."""
    errors = exc.errors()
    if not errors:
        return "invalid input"

    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()))
    msg = str(first.get("msg", "invalid input"))
    return f"{loc}: {msg}" if loc else msg
