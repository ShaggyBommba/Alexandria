from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MaxDocsFullness:
    """Marks a leaf full when its local document count reaches the limit."""

    max_docs: int

    def full(self, doc_count: int) -> bool:
        return doc_count >= self.max_docs
