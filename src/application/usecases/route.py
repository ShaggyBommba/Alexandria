from __future__ import annotations

from application.ports import NodeHit, NodeRepo


class Route:
    """Walks the tree from root to candidate leaves.

    Flow: start at the root, use embedding distance over children, keep a beam
    of promising paths, and return several leaf candidates for later expansion.

    Implementation contract:

    - Use only the `NodeRepo` port. This use case decides traversal policy;
      repositories only fetch nodes and similarity hits.
    - Start with `nodes.root()`. If there is no active root or `limit <= 0`,
      return an empty list.
    - Branch nodes should be expanded with `nodes.near(...)` scoped to the
      branch parent. Leaf nodes become route candidates.
    - Return at most `limit` `NodeHit` values, ordered by closest distance with
      deterministic tie handling, and avoid revisiting nodes already seen in
      the traversal.
    """

    def __init__(self, nodes: NodeRepo | None = None) -> None:
        self.nodes = nodes

    async def run(self, embedding: list[float], limit: int = 10) -> list[NodeHit]:
        """Return candidate leaf nodes for one embedding."""
        raise NotImplementedError("Route.run is not implemented yet")
