from __future__ import annotations

from uuid import UUID

from application.ports import UnitOfWork


class Refs:
    """Rebuilds directed semantic references for a node.

    Flow: clear stale outgoing references, compare the node with active leaves,
    and store the strongest directed links used to widen retrieval scope.

    Implementation contract:

    - Use the configured `UnitOfWork`; reference rebuilds are durable writes and
      should commit through that transaction boundary.
    - Load the source node from `uow.nodes.get(node_id)`. If it is missing or is
      not an active leaf, leave references unchanged.
    - Find nearby active leaf candidates using the source embedding, excluding
      the source node so self-references are never created.
    - Replace outgoing references through `uow.refs.set(...)` rather than
      clearing and appending piecemeal. Preserve deterministic rank order from
      the nearest candidates and cap the replacement set by `limit`.
    """

    def __init__(self, uow: UnitOfWork | None = None) -> None:
        self.uow = uow

    async def run(self, node_id: UUID, limit: int = 10) -> None:
        """Replace outgoing references for one active leaf node."""
        raise NotImplementedError("Refs.run is not implemented yet")
