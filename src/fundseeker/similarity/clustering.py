"""Clustering algorithms implemented with NumPy only.

The project environment does not include scipy or scikit-learn, so we provide a
lightweight K-Means++ implementation here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class KMeansResult:
    """Result of a K-Means clustering run."""

    labels: np.ndarray
    centroids: np.ndarray
    inertia: float
    n_iter: int
    silhouette: float | None = None


def _squared_distances(X: np.ndarray, centers: np.ndarray) -> np.ndarray:
    """Return (n_samples, n_centers) squared Euclidean distances."""
    # (x - c)^2 = x^2 + c^2 - 2xc
    x_sq = np.sum(X * X, axis=1, keepdims=True)
    c_sq = np.sum(centers * centers, axis=1, keepdims=True).T
    cross = X @ centers.T
    return np.maximum(x_sq + c_sq - 2.0 * cross, 0.0)


def _kmeans_plus_plus(X: np.ndarray, k: int, seed: int) -> np.ndarray:
    """Initialize K-Means centroids using K-Means++."""
    rng = np.random.default_rng(seed)
    n_samples = X.shape[0]
    centers = np.empty((k, X.shape[1]), dtype=X.dtype)

    # First center: random sample.
    first_idx = rng.integers(n_samples)
    centers[0] = X[first_idx]

    # Subsequent centers: proportional to squared distance from nearest center.
    closest_dist_sq = np.full(n_samples, np.inf)
    for i in range(1, k):
        dist_sq = np.sum((X - centers[i - 1]) ** 2, axis=1)
        closest_dist_sq = np.minimum(closest_dist_sq, dist_sq)
        # Avoid numerical issues by ensuring non-negative.
        closest_dist_sq = np.maximum(closest_dist_sq, 0.0)
        total = closest_dist_sq.sum()
        if total == 0:
            centers[i] = X[rng.integers(n_samples)]
            continue
        probs = closest_dist_sq / total
        next_idx = rng.choice(n_samples, p=probs)
        centers[i] = X[next_idx]

    return centers


def kmeans(
    X: np.ndarray,
    k: int,
    seed: int = 42,
    max_iter: int = 100,
    tol: float = 1e-4,
    init: str = "k-means++",
) -> KMeansResult:
    """Run K-Means clustering on a dense matrix.

    Args:
        X: (n_samples, n_features) data matrix.
        k: Number of clusters.
        seed: Random seed for initialization.
        max_iter: Maximum number of iterations.
        tol: Convergence threshold for centroid movement.
        init: "k-means++" or "random".

    Returns:
        KMeansResult with labels, centroids, inertia, iterations and silhouette.
    """
    if k <= 0 or k > X.shape[0]:
        raise ValueError(f"Invalid k={k} for n_samples={X.shape[0]}")

    if init == "k-means++":
        centers = _kmeans_plus_plus(X, k, seed)
    elif init == "random":
        rng = np.random.default_rng(seed)
        idx = rng.choice(X.shape[0], size=k, replace=False)
        centers = X[idx].copy()
    else:
        raise ValueError(f"Unknown init: {init}")

    labels = np.empty(X.shape[0], dtype=np.int64)
    inertia = np.inf
    n_iter = 0

    for iteration in range(max_iter):
        dist_sq = _squared_distances(X, centers)
        labels = np.argmin(dist_sq, axis=1)
        inertia = np.sum(dist_sq[np.arange(X.shape[0]), labels])

        new_centers = np.zeros_like(centers)
        for c in range(k):
            mask = labels == c
            if np.any(mask):
                new_centers[c] = X[mask].mean(axis=0)
            else:
                # Empty cluster: re-initialize to the point farthest from all
                # current centers.  This is more stable than a random draw and
                # avoids immediately collapsing back into an existing cluster.
                dist_sq = _squared_distances(X, centers)
                farthest_idx = int(np.argmax(dist_sq.min(axis=1)))
                new_centers[c] = X[farthest_idx]

        shift = np.linalg.norm(centers - new_centers)
        centers = new_centers
        n_iter = iteration + 1

        if shift < tol:
            break

    silhouette = compute_silhouette(X, labels)
    return KMeansResult(
        labels=labels,
        centroids=centers,
        inertia=float(inertia),
        n_iter=n_iter,
        silhouette=silhouette,
    )


def compute_silhouette(
    X: np.ndarray,
    labels: np.ndarray,
    distances: np.ndarray | None = None,
) -> float | None:
    """Compute mean silhouette score for a clustering.

    Args:
        X: (n_samples, n_features) data matrix.
        labels: Cluster label for each sample.
        distances: Optional precomputed (n_samples, n_samples) Euclidean distance
            matrix.  When ``select_k_silhouette`` evaluates many k values, the
            matrix can be computed once and reused.
    """
    unique_labels = np.unique(labels)
    if len(unique_labels) <= 1 or len(unique_labels) >= X.shape[0]:
        return None

    n = X.shape[0]
    a = np.zeros(n)
    b = np.full(n, np.inf)

    if distances is None:
        # Precompute pairwise squared distances for small-to-medium data.
        # For very large N, this should be replaced by block computation.
        dist_sq = (
            np.sum(X * X, axis=1).reshape(-1, 1)
            + np.sum(X * X, axis=1).reshape(1, -1)
            - 2.0 * (X @ X.T)
        )
        dist_sq = np.maximum(dist_sq, 0.0)
        distances = np.sqrt(dist_sq)

    for i in range(n):
        same_mask = labels == labels[i]
        same_count = same_mask.sum() - 1
        if same_count > 0:
            a[i] = distances[i, same_mask].sum() / same_count

        for c in unique_labels:
            if c == labels[i]:
                continue
            other_mask = labels == c
            if np.any(other_mask):
                other_mean = distances[i, other_mask].mean()
                b[i] = min(b[i], other_mean)

    scores = (b - a) / np.maximum(a, b)
    return float(np.mean(scores))


def select_k_silhouette(
    X: np.ndarray,
    k_min: int,
    k_max: int,
    seed: int = 42,
    max_iter: int = 100,
    tol: float = 1e-4,
) -> dict[str, Any]:
    """Run K-Means for a range of k and select the best by silhouette score.

    The pairwise distance matrix is computed once and reused for every k,
    avoiding repeated O(n^2) work during model selection.

    Returns:
        dict with keys: best_k, best_result, results (list of dicts).
    """
    # Precompute the full distance matrix once.
    dist_sq = (
        np.sum(X * X, axis=1).reshape(-1, 1)
        + np.sum(X * X, axis=1).reshape(1, -1)
        - 2.0 * (X @ X.T)
    )
    dist_sq = np.maximum(dist_sq, 0.0)
    distances = np.sqrt(dist_sq)

    results: list[dict[str, Any]] = []
    result_objects: dict[int, KMeansResult] = {}
    best_k = k_min
    best_score = -1.0
    best_result = None

    for k in range(k_min, k_max + 1):
        result = kmeans(X, k=k, seed=seed, max_iter=max_iter, tol=tol)
        # Recompute silhouette using the cached distance matrix.
        result.silhouette = compute_silhouette(X, result.labels, distances=distances)
        score = result.silhouette if result.silhouette is not None else -1.0
        results.append(
            {
                "k": k,
                "inertia": result.inertia,
                "silhouette": score,
                "n_iter": result.n_iter,
            }
        )
        result_objects[k] = result
        if score > best_score:
            best_score = score
            best_k = k
            best_result = result

    return {
        "best_k": best_k,
        "best_result": best_result,
        "results": results,
        "result_objects": result_objects,
    }


def _normalize_series(values: list[float]) -> list[float]:
    """Min-max normalize a list of floats into [0, 1]."""
    min_v = min(values)
    max_v = max(values)
    if max_v == min_v:
        return [0.5] * len(values)
    return [(v - min_v) / (max_v - min_v) for v in values]


def select_k_elbow(
    X: np.ndarray,
    k_min: int,
    k_max: int,
    elbow_weight: float = 0.3,
    seed: int = 42,
    max_iter: int = 100,
    tol: float = 1e-4,
) -> dict[str, Any]:
    """Select K using a silhouette + inertia-elbow composite score.

    The silhouette score rewards well-separated clusters.  The inertia elbow
    score rewards the ``knee`` where adding another cluster yields sharply
    diminishing reductions in SSE.  The composite combines them so that the
    chosen K is both compact and interpretable.

    Args:
        X: Data matrix.
        k_min, k_max: Search range (inclusive).
        elbow_weight: How much to weight the normalized elbow score (0..1).
        seed, max_iter, tol: Passed to ``kmeans``.

    Returns:
        dict with keys: best_k, best_result, results (list of dicts),
        selection_method.
    """
    raw = select_k_silhouette(
        X,
        k_min=k_min,
        k_max=k_max,
        seed=seed,
        max_iter=max_iter,
        tol=tol,
    )
    results = raw["results"]

    if len(results) < 2:
        return {
            "best_k": raw["best_k"],
            "best_result": raw["best_result"],
            "results": results,
            "selection_method": "silhouette_only",
        }

    ks = [r["k"] for r in results]
    silhouettes = [r["silhouette"] for r in results]
    inertias = [r["inertia"] for r in results]

    silhouette_norm = _normalize_series(silhouettes)

    # Inertia: lower is better, but the *marginal* improvement matters.  We use
    # the maximum curvature heuristic (second derivative of the log-inertia
    # curve) as a simple elbow indicator.
    log_inertias = [np.log(max(i, 1e-12)) for i in inertias]
    curvature: list[float] = [0.0] * len(ks)
    for i in range(1, len(ks) - 1):
        left_slope = log_inertias[i] - log_inertias[i - 1]
        right_slope = log_inertias[i + 1] - log_inertias[i]
        # Second derivative approximates curvature.
        curvature[i] = left_slope - right_slope
    curvature_norm = _normalize_series(curvature)

    composite_scores = [
        silhouette_norm[i] + elbow_weight * curvature_norm[i]
        for i in range(len(ks))
    ]

    best_idx = int(np.argmax(composite_scores))
    best_k = ks[best_idx]

    # Reuse the already-computed result object for the chosen k.
    best_result = raw["result_objects"][best_k]
    best_result.silhouette = silhouettes[best_idx]

    return {
        "best_k": best_k,
        "best_result": best_result,
        "results": results,
        "selection_method": "silhouette_elbow_composite",
    }


def kmeans_from_centroids(
    X: np.ndarray,
    centroids: np.ndarray,
    max_iter: int = 100,
    tol: float = 1e-4,
) -> KMeansResult:
    """Run standard K-Means initialized from existing centroids.

    .. important::
        This is **NOT** a partial incremental update.  It runs the full
        assign-then-update K-Means loop on *all* samples, using the provided
        centroids only as the starting point (warm start).  The benefit is
        faster convergence and more reproducible cluster assignments compared
        to a random K-Means++ initialization.

    The centroid matrix is aligned to the feature space of ``X`` by the caller.

    Args:
        X: (n_samples, n_features) data matrix.
        centroids: (k, n_features) baseline centroids.
        max_iter: Maximum number of iterations.
        tol: Convergence threshold for centroid movement.

    Returns:
        KMeansResult with labels, centroids, inertia, iterations and silhouette.
    """
    k, n_features = centroids.shape
    if X.shape[1] != n_features:
        raise ValueError(
            f"Feature dimension mismatch: X has {X.shape[1]}, "
            f"centroids have {n_features}"
        )
    if k <= 0 or k > X.shape[0]:
        raise ValueError(f"Invalid k={k} for n_samples={X.shape[0]}")

    centers = centroids.copy()
    labels = np.empty(X.shape[0], dtype=np.int64)
    inertia = np.inf
    n_iter = 0

    for iteration in range(max_iter):
        dist_sq = _squared_distances(X, centers)
        labels = np.argmin(dist_sq, axis=1)
        inertia = np.sum(dist_sq[np.arange(X.shape[0]), labels])

        new_centers = np.zeros_like(centers)
        for c in range(k):
            mask = labels == c
            if np.any(mask):
                new_centers[c] = X[mask].mean(axis=0)
            else:
                # Empty cluster: keep the old centroid to preserve semantics.
                new_centers[c] = centers[c]

        shift = np.linalg.norm(centers - new_centers)
        centers = new_centers
        n_iter = iteration + 1

        if shift < tol:
            break

    silhouette = compute_silhouette(X, labels)
    return KMeansResult(
        labels=labels,
        centroids=centers,
        inertia=float(inertia),
        n_iter=n_iter,
        silhouette=silhouette,
    )
