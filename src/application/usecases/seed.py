from __future__ import annotations

from application.exceptions import MissingUnitOfWork
from application.ports import UnitOfWork
from domain.entity import VECTOR_DIMENSIONS, Node


class Seed:
    """Creates the root node when the index is empty.

    Flow: find the existing root or create the first stable entrypoint used by
    both ingest routing and retrieval routing.

    Implementation contract:

    - Use the configured `UnitOfWork`; seeding writes durable state and must
      commit through that transaction boundary.
    - Return `uow.nodes.root()` when an active parentless root already exists.
      Do not create duplicate roots.
    - When no root exists, create one active leaf node with no parent, stable
      name and description values, and a deterministic valid embedding vector
      that satisfies the current `Node` model.
    - Persist the root through `uow.nodes.add(...)`, commit once, and return the
      created root. Do not call external providers or infrastructure adapters
      outside the unit-of-work boundary.
    """

    def __init__(self, uow: UnitOfWork | None = None) -> None:
        self.uow = uow

    async def run(self) -> Node:
        """Return the existing root or create the first root node."""
        if self.uow is None:
            raise MissingUnitOfWork("Seed requires a UnitOfWork")

        uow = self.uow
        root = await uow.nodes.root()
        if root is not None:
            return root

        root = Node(
            parent_id=None,
            name="Root",
            description="Stable root for the Alexandria semantic index.",
            embedding=[1.0] + [0.0] * (VECTOR_DIMENSIONS - 1),
            kind="leaf",
            status="active",
        )
        await uow.nodes.add(root)
        await uow.commit()
        return root
