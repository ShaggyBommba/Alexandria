from __future__ import annotations

from domain.entity import Node

from application.ports import UnitOfWork


class Seed:
    """Creates the root node when the index is empty.

    Flow: find the existing root or create the first stable entrypoint used by
    both ingest routing and retrieval routing.
    """

    def __init__(self, uow: UnitOfWork | None = None) -> None:
        self.uow = uow

    async def run(self) -> Node:
        """Return the existing root or create the first root node."""
        raise NotImplementedError("Seed.run is not implemented yet")
