from __future__ import annotations

import logging
from uuid import UUID

from application.exceptions import LintDependencyError, MissingUnitOfWork
from application.ports import FullnessPolicy, UnitOfWork
from application.usecases.split import Split

logger = logging.getLogger(__name__)


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
        logger.info("lint started node_id=%s", node_id)
        if self.uow is None:
            raise MissingUnitOfWork("Lint requires a UnitOfWork")
        if self.split is None:
            raise LintDependencyError("Lint requires a Split use case")
        if self.fullness is None:
            raise LintDependencyError("Lint requires a FullnessPolicy")

        node = await self.uow.nodes.get(node_id)
        if node is None or node.status != "active" or node.kind != "leaf":
            logger.info("lint skipped ineligible node_id=%s", node_id)
            return

        doc_count = await self.uow.nodes.count(node.id)
        if not self.fullness.full(doc_count):
            logger.info("lint skipped not full node_id=%s doc_count=%s", node_id, doc_count)
            return

        logger.info("lint delegating split node_id=%s doc_count=%s", node_id, doc_count)
        await self.split.run(node.id)
