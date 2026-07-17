"""Pairwise similarity metrics for portfolio holding vectors."""

from __future__ import annotations

from typing import Any

import numpy as np

from fundseeker.similarity.features import FeatureMatrix


def overlap_coefficient(a: np.ndarray, b: np.ndarray) -> float:
    """Sum of element-wise minima, the default business-facing metric."""
    return float(np.sum(np.minimum(a, b)))


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two dense vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def jaccard_index(a: np.ndarray, b: np.ndarray) -> float:
    """Jaccard index over non-zero positions (ignores weights)."""
    mask_a = a != 0
    mask_b = b != 0
    intersection = np.logical_and(mask_a, mask_b).sum()
    union = np.logical_or(mask_a, mask_b).sum()
    if union == 0:
        return 0.0
    return float(intersection / union)


_METRICS = {
    "overlap": overlap_coefficient,
    "cosine": cosine_similarity,
    "jaccard": jaccard_index,
}


def find_neighbors(
    fm: FeatureMatrix,
    target_product_id: int,
    top_n: int = 10,
    metric: str = "overlap",
    use_raw_weights: bool = False,
) -> list[dict[str, Any]]:
    """Return the most similar products to ``target_product_id``.

    Args:
        fm: Feature matrix built from holdings.
        target_product_id: Product to query.
        top_n: Number of neighbors to return.
        metric: One of ``overlap``, ``cosine``, ``jaccard``.
        use_raw_weights: If True, use ``fm.raw_weights`` instead of the
            normalized ``fm.X``.  Recommended for ``overlap`` and ``jaccard``
            so scores stay in the [0, 1] range.

    Returns:
        List of neighbor dicts sorted by similarity descending.
    """
    if metric not in _METRICS:
        raise ValueError(f"Unknown metric: {metric}")
    fn = _METRICS[metric]
    matrix = fm.raw_weights if use_raw_weights else fm.X

    target_idx = np.where(fm.product_ids == target_product_id)[0]
    if len(target_idx) == 0:
        raise ValueError(f"product_id {target_product_id} not found in feature matrix")
    target_idx = int(target_idx[0])
    target_vec = matrix[target_idx]

    scores: list[tuple[int, float]] = []
    for i in range(fm.n_products):
        if i == target_idx:
            continue
        score = fn(target_vec, matrix[i])
        scores.append((i, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    neighbors: list[dict[str, Any]] = []
    for i, score in scores[:top_n]:
        neighbors.append(
            {
                "product_id": int(fm.product_ids[i]),
                "product_code": str(fm.product_codes[i]),
                "product_name": str(fm.product_names[i]),
                "institution_code": str(fm.institution_codes[i]),
                "metric": metric,
                "score": score,
            }
        )
    return neighbors
