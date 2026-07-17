"""Default configuration for the similarity service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClusterConfig:
    """Configuration for clustering runs."""

    algorithm: str = "kmeans"
    # Number of clusters. Use "auto" to select via silhouette score.
    k: int | str = "auto"
    k_min: int = 3
    k_max: int = 12
    random_seed: int = 42
    max_iter: int = 100
    # Convergence threshold for centroid movement.
    tol: float = 1e-4
    # Minimum number of holdings for a product to be included.
    min_holdings: int = 3
    # Product types to include in clustering.
    product_types: tuple[str, ...] = ("equity", "mixed")
    # Asset types to use for building the weight vector.
    asset_types: tuple[str, ...] = ("stock",)
    # L2-normalize weight vectors before clustering.
    normalize: bool = True


@dataclass
class IncrementalConfig:
    """Configuration for incremental / full clustering switching."""

    # Default mode: "auto" falls back to full when no baseline exists, otherwise
    # incremental; "full" always reruns k selection; "incremental" always uses
    # the latest baseline and refuses to run if none exists.
    mode: str = "auto"
    # Thresholds for triggering automatic fallback from incremental to full.
    # A fallback is triggered when ANY of the following is violated.
    silhouette_min: float = 0.05
    silhouette_drop_ratio: float = 0.25
    inertia_change_ratio: float = 0.50
    n_products_change_ratio: float = 0.20
    feature_jaccard_min: float = 0.80
    # Weight for the elbow heuristic when selecting K during a full run.
    # score = silhouette_score + elbow_weight * normalized_elbow_score.
    elbow_weight: float = 0.3


@dataclass
class SimilarityConfig:
    """Top-level configuration for the similarity service."""

    cluster: ClusterConfig = field(default_factory=ClusterConfig)
    incremental: IncrementalConfig = field(default_factory=IncrementalConfig)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "cluster": {
                "algorithm": self.cluster.algorithm,
                "k": self.cluster.k,
                "k_min": self.cluster.k_min,
                "k_max": self.cluster.k_max,
                "random_seed": self.cluster.random_seed,
                "max_iter": self.cluster.max_iter,
                "tol": self.cluster.tol,
                "min_holdings": self.cluster.min_holdings,
                "product_types": list(self.cluster.product_types),
                "asset_types": list(self.cluster.asset_types),
                "normalize": self.cluster.normalize,
            },
            "incremental": {
                "mode": self.incremental.mode,
                "silhouette_min": self.incremental.silhouette_min,
                "silhouette_drop_ratio": self.incremental.silhouette_drop_ratio,
                "inertia_change_ratio": self.incremental.inertia_change_ratio,
                "n_products_change_ratio": self.incremental.n_products_change_ratio,
                "feature_jaccard_min": self.incremental.feature_jaccard_min,
                "elbow_weight": self.incremental.elbow_weight,
            },
        }


DEFAULT_CONFIG = SimilarityConfig()
