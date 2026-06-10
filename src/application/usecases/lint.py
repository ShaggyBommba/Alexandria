from __future__ import annotations

from uuid import UUID

from application.exceptions import LintDependencyError, MissingUnitOfWork
from application.ports import FullnessPolicy, UnitOfWork
from application.usecases.split import Split


class Lint:
    """Checks whether a queued node still needs splitting.

    Flow: reload the queued node after claim, verify the current durable state,
    skip stale work, and delegate to split only when the leaf is still full.
    """

    def __init__(
        self,
        uow: UnitOfWork | None = None,
        split: Split | None = None,
        fullness: FullnessPolicy | None = None,
    ) -> None:
        self.uow = uow
        self.split = split
        self.fullness = fullness

    async def run(self, node_id: UUID) -> None:
        """Evaluate one split-check job and delegate splitting if needed."""
        if self.uow is None:
            raise MissingUnitOfWork("Lint requires a UnitOfWork")
        if self.split is None:
            raise LintDependencyError("Lint requires a Split use case")
        if self.fullness is None:
            raise LintDependencyError("Lint requires a FullnessPolicy")

        node = await self.uow.nodes.get(node_id)
        if node is None or node.status != "active" or node.kind != "leaf":
            return

        doc_count = await self.uow.nodes.count(node.id)
        if not self.fullness.full(doc_count):
            return

        await self.split.run(node.id)
