from __future__ import annotations

from uuid import UUID

from application.ports import UnitOfWork
from application.usecases.split import Split


class Lint:
    """Checks whether a queued node still needs splitting."""

    def __init__(
        self,
        uow: UnitOfWork | None = None,
        split: Split | None = None,
    ) -> None:
        self.uow = uow
        self.split = split

    async def run(self, node_id: UUID) -> None:
        """Evaluate one split-check job and delegate splitting if needed."""
        raise NotImplementedError("Lint.run is not implemented yet")
