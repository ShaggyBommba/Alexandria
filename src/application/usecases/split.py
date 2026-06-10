from __future__ import annotations

from uuid import UUID

from application.exceptions import MissingUnitOfWork, SplitDependencyError, SplitPlanError
from application.ports import ChildPlan, FullnessPolicy, SplitPlan, Splitter, UnitOfWork
from domain.entity import Document, Node


class Split:
    """Splits a full leaf into child nodes and redistributes documents.

    Flow: load the full leaf, ask the splitter for child plans, validate those
    plans against local documents, move documents, and clear stale outgoing refs.
    """

    def __init__(
        self,
        uow: UnitOfWork | None = None,
        splitter: Splitter | None = None,
        fullness: FullnessPolicy | None = None,
    ) -> None:
        self.uow = uow
        self.splitter = splitter
        self.fullness = fullness

    async def run(self, node_id: UUID) -> None:
        """Split one node after validating local documents and assignments."""
        if self.uow is None:
            raise MissingUnitOfWork("Split requires a UnitOfWork")
        if self.splitter is None:
            raise SplitDependencyError("Split requires a Splitter")
        if self.fullness is None:
            raise SplitDependencyError("Split requires a FullnessPolicy")

        uow = self.uow
        source = await uow.nodes.get(node_id)
        if not self.eligible(source):
            return

        docs = await uow.docs.leaf(node_id)
        if not self.fullness.full(len(docs)):
            return

        split_source = copy_node(source)
        split_docs = [copy_doc(doc) for doc in docs]
        source.status = "splitting"
        source.doc_count = len(docs)
        await uow.nodes.save(source)
        await uow.commit()

        try:
            plan = await self.splitter.split(split_source, split_docs)
        except Exception:
            await self.release(node_id)
            raise

        source = await uow.nodes.get(node_id)
        if not self.claimed(source):
            await uow.rollback()
            return

        docs = await uow.docs.leaf(node_id)
        if not self.fullness.full(len(docs)):
            await self.release(node_id)
            return

        try:
            children = self.validate(plan, docs)
        except SplitPlanError:
            await self.release(node_id)
            raise

        for child in children:
            child_node = Node(
                parent_id=source.id,
                name=child.name,
                description=child.description,
                embedding=list(child.embedding),
                kind="leaf",
                status="active",
                doc_count=len(child.docs),
            )
            child_id = await uow.nodes.add(child_node)
            await uow.docs.move(list(child.docs), child_id)

        source.kind = "branch"
        source.status = "active"
        source.doc_count = 0
        source.version += 1
        await uow.refs.clear(source.id)
        await uow.nodes.save(source)
        await uow.commit()

    def eligible(self, node: Node | None) -> bool:
        """Return whether a node is a current leaf candidate for splitting."""
        return node is not None and node.status == "active" and node.kind == "leaf"

    def claimed(self, node: Node | None) -> bool:
        """Return whether this split still owns a claimed source leaf."""
        return node is not None and node.status == "splitting" and node.kind == "leaf"

    async def release(self, node_id: UUID) -> None:
        """Release a split claim when no child writes can be committed."""
        if self.uow is None:
            raise MissingUnitOfWork("Split requires a UnitOfWork")

        source = await self.uow.nodes.get(node_id)
        if source is None or source.kind != "leaf" or source.status != "splitting":
            await self.uow.rollback()
            return

        docs = await self.uow.docs.leaf(node_id)
        source.status = "active"
        source.doc_count = len(docs)
        await self.uow.nodes.save(source)
        await self.uow.commit()

    def validate(self, plan: SplitPlan, docs: list[Document]) -> list[ChildPlan]:
        """Validate an untrusted split plan against current local documents."""
        if not isinstance(plan, SplitPlan):
            raise SplitPlanError("Splitter returned an invalid SplitPlan")
        if not plan.children:
            raise SplitPlanError("SplitPlan must include at least one child")

        local_ids = {doc.id for doc in docs}
        assigned: set[UUID] = set()
        children: list[ChildPlan] = []

        for child in plan.children:
            if not isinstance(child, ChildPlan):
                raise SplitPlanError("SplitPlan contains an invalid child")
            if not child.docs:
                raise SplitPlanError("SplitPlan child must assign documents")

            for doc_id in child.docs:
                if doc_id not in local_ids:
                    raise SplitPlanError(f"SplitPlan assigned unknown document {doc_id}")
                if doc_id in assigned:
                    raise SplitPlanError(
                        f"SplitPlan assigned document {doc_id} more than once"
                    )
                assigned.add(doc_id)

            children.append(child)

        missing = local_ids - assigned
        if missing:
            missing_ids = ", ".join(str(id) for id in sorted(missing))
            raise SplitPlanError(
                f"SplitPlan left local documents unassigned: {missing_ids}"
            )

        return children


def copy_node(node: Node) -> Node:
    """Return a detached node snapshot for splitter input."""
    return Node(
        id=node.id,
        parent_id=node.parent_id,
        name=node.name,
        description=node.description,
        embedding=list(node.embedding),
        kind=node.kind,
        status=node.status,
        doc_count=node.doc_count,
        version=node.version,
    )


def copy_doc(doc: Document) -> Document:
    """Return a detached document snapshot for splitter input."""
    return Document(
        id=doc.id,
        leaf_id=doc.leaf_id,
        source_key=doc.source_key,
        name=doc.name,
        summary=doc.summary,
        body=doc.body,
        embedding=list(doc.embedding),
    )
