from __future__ import annotations

from application.exceptions import RouteDependencyError
from application.ports import NodeHit, NodeRepo


def hit_order(hit: NodeHit) -> tuple[float, str]:
    """Sort hits by closest distance with stable node-id ties."""
    return (hit.distance, str(hit.node.id))


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
        if self.nodes is None:
            raise RouteDependencyError("Route requires a NodeRepo dependency")

        if limit <= 0:
            return []

        root = await self.nodes.root()
        if root is None:
            return []

        if root.kind == "leaf":
            if root.status != "active":
                return []
            return [NodeHit(root, 0.0)]

        if root.kind != "branch" or root.status != "active":
            return []

        seen = {root.id}
        branches = [NodeHit(root, 0.0)]
        leaves: list[NodeHit] = []

        while branches:
            branch = branches.pop(0)
            hits = await self.nodes.near(
                embedding,
                limit=limit,
                parent=branch.node.id,
                exclude=set(seen),
            )

            for hit in sorted(hits, key=hit_order):
                node_id = hit.node.id
                if node_id in seen:
                    continue

                seen.add(node_id)
                if hit.node.status != "active":
                    continue

                if hit.node.kind == "leaf":
                    leaves.append(hit)
                elif hit.node.kind == "branch":
                    branches.append(hit)

            branches.sort(key=hit_order)

        return sorted(leaves, key=hit_order)[:limit]
