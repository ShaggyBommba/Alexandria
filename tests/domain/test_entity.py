from __future__ import annotations

from uuid import UUID

from domain.entity import Document, Job, Node, Reference
from domain.values import JobKind, JobStatus


def test_node_defaults_to_active_leaf() -> None:
    node = Node(
        name="Research",
        description="Documents about research workflows.",
        embedding=[0.1, 0.2, 0.3],
    )

    assert isinstance(node.id, UUID)
    assert node.parent is None
    assert node.parent_id is None
    assert node.name == "Research"
    assert node.description == "Documents about research workflows."
    assert node.embedding == [0.1, 0.2, 0.3]
    assert node.kind == "leaf"
    assert node.status == "active"
    assert node.doc_count == 0
    assert node.version == 1


def test_document_attaches_to_leaf_node() -> None:
    leaf = Node(
        name="Research",
        description="Documents about research workflows.",
        embedding=[0.1, 0.2, 0.3],
    )
    doc = Document(
        leaf=leaf,
        name="Beam search notes",
        summary="Notes about using beam search for routing.",
        body="Beam search keeps multiple candidate paths through the tree.",
        embedding=[0.4, 0.5, 0.6],
    )

    assert isinstance(doc.id, UUID)
    assert doc.leaf is leaf
    assert leaf.documents == [doc]
    assert doc.name == "Beam search notes"
    assert doc.summary == "Notes about using beam search for routing."
    assert doc.body == "Beam search keeps multiple candidate paths through the tree."
    assert doc.embedding == [0.4, 0.5, 0.6]


def test_reference_links_nodes_directionally() -> None:
    source = Node(
        name="Search",
        description="Documents about search workflows.",
        embedding=[0.1, 0.2, 0.3],
    )
    target = Node(
        name="Ranking",
        description="Documents about ranking workflows.",
        embedding=[0.4, 0.5, 0.6],
    )
    ref = Reference(
        from_node=source,
        to_node=target,
        distance=0.12,
        rank=0,
    )

    assert isinstance(ref.id, UUID)
    assert ref.from_node is source
    assert ref.to_node is target
    assert source.references == [ref]
    assert target.referenced_by == [ref]
    assert ref.distance == 0.12
    assert ref.rank == 0
    assert ref.method == "embedding"


def test_job_defaults_to_pending() -> None:
    key = UUID("00000000-0000-0000-0000-000000000001")

    job = Job(kind=JobKind.EMAIL_SEND, payload={"to": "user@example.com"}, key=key)

    assert isinstance(job.id, UUID)
    assert job.kind in {JobKind.EMAIL_SEND, JobKind.EMAIL_SEND.value}
    assert job.key == key
    assert job.payload == {"to": "user@example.com"}
    assert job.status in {JobStatus.PENDING, JobStatus.PENDING.value}
    assert job.attempts == 0
    assert job.max_attempts == 3


def test_job_accepts_raw_kind_and_status_strings() -> None:
    job = Job(
        kind="email.send",
        payload={},
        key="00000000-0000-0000-0000-000000000001",
        status="running",
    )

    assert job.kind == "email.send"
    assert job.status == "running"
    assert job.key == UUID("00000000-0000-0000-0000-000000000001")


def test_job_accepts_uuid_key_from_string() -> None:
    assert isinstance(
        Job(
            kind="email.send",
            payload={},
            key="00000000-0000-0000-0000-000000000002",
        ).key,
        UUID,
    )
