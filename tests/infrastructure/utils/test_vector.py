from __future__ import annotations

import pytest

from infrastructure.utils.vector import cosine_distance


def test_cosine_distance_scores_same_and_orthogonal_vectors() -> None:
    assert cosine_distance([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)
    assert cosine_distance([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)


def test_cosine_distance_returns_infinity_for_zero_vector() -> None:
    assert cosine_distance([0.0, 0.0], [1.0, 0.0]) == float("inf")


def test_cosine_distance_rejects_mismatched_dimensions() -> None:
    with pytest.raises(ValueError):
        cosine_distance([1.0], [1.0, 0.0])
