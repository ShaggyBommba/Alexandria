from __future__ import annotations

from uuid import UUID

from application.ports import Splitter, UnitOfWork


class Split:
    """Splits a full leaf into child nodes and redistributes documents."""

    def __init__(
        self,
        uow: UnitOfWork | None = None,
        splitter: Splitter | None = None,
    ) -> None:
        self.uow = uow
        self.splitter = splitter

    async def run(self, node_id: UUID) -> None:
        """Split one node after validating local documents and assignments."""
        raise NotImplementedError("Split.run is not implemented yet")
