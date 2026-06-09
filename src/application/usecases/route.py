from __future__ import annotations

from application.ports import NodeHit, NodeRepo


class Route:
    """Walks the tree from root to candidate leaves.

    Flow: start at the root, use embedding distance over children, keep a beam
    of promising paths, and return several leaf candidates for later expansion.
    """

    def __init__(self, nodes: NodeRepo | None = None) -> None:
        self.nodes = nodes

    async def run(self, embedding: list[float], limit: int = 10) -> list[NodeHit]:
        """Return candidate leaves for one embedding."""
        raise NotImplementedError("Route.run is not implemented yet")
