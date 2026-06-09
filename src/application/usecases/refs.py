from __future__ import annotations

from uuid import UUID

from application.ports import UnitOfWork


class Refs:
    """Rebuilds directed semantic references for a node."""

    def __init__(self, uow: UnitOfWork | None = None) -> None:
        self.uow = uow

    async def run(self, node_id: UUID, limit: int = 10) -> None:
        """Replace the outgoing references for one node."""
        raise NotImplementedError("Refs.run is not implemented yet")
