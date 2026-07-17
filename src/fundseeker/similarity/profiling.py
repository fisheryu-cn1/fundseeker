"""Cluster profiling: generate human-readable summaries for each cluster."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from fundseeker.similarity.clustering import KMeansResult
from fundseeker.similarity.features import FeatureMatrix, compute_hhi
from fundseeker.similarity.industry import IndustryMapping
from fundseeker.similarity.labels import derive_cluster_label


@dataclass
class ClusterProfile:
    """Profile for a single cluster."""

    cluster_id: int
    size: int
    cluster_label: str | None = None
    top_holdings: list[dict[str, Any]] = field(default_factory=list)
    top_industries: list[dict[str, Any]] = field(default_factory=list)
    avg_hhi: float = 0.0
    avg_overlap: float = 0.0
    avg_overlap_raw: float = 0.0
    ac_share_dominance_ratio: float = 0.0
    institution_distribution: dict[str, int] = field(default_factory=dict)
    representative_products: list[int] = field(default_factory=list)
    representative_codes: list[str] = field(default_factory=list)
    representative_names: list[str] = field(default_factory=list)


def _overlap_pairwise(X: np.ndarray) -> float:
    """Compute mean overlap coefficient over all pairs in a cluster.

    The overlap coefficient is ``sum_k min(w_i,k, w_j,k)``.  The input matrix
    ``X`` may contain L2-normalized vectors or raw weight vectors; the caller
    is responsible for documenting which semantic is used.
    """
    n = X.shape[0]
    if n < 2:
        return 0.0
    total = 0.0
    for k in range(X.shape[1]):
        col = X[:, k]
        sorted_col = np.sort(col)
        pair_sum = np.sum(sorted_col * (n - 1 - np.arange(n)))
        total += pair_sum
    n_pairs = n * (n - 1) / 2.0
    return float(total / n_pairs)


def _derive_top_industries_from_assets(
    fm: FeatureMatrix,
    centroid: np.ndarray,
    mapping: IndustryMapping,
    top_n: int,
) -> list[dict[str, Any]]:
    """Aggregate centroid asset weights into industry weights."""
    industry_weights: dict[str, float] = {}
    for i, weight in enumerate(centroid):
        if weight <= 0:
            continue
        asset_code = str(fm.feature_names[i])
        market = _infer_market_for_asset(fm, i)
        industry = mapping.get(asset_code, market)
        if industry is None:
            industry = "未知行业"
        industry_weights[industry] = industry_weights.get(industry, 0.0) + float(weight)

    sorted_items = sorted(industry_weights.items(), key=lambda x: x[1], reverse=True)
    return [
        {"industry": name, "weight": weight}
        for name, weight in sorted_items[:top_n]
    ]


def _infer_market_for_asset(fm: FeatureMatrix, feature_idx: int) -> str:
    """Best-effort market inference when not stored in the matrix."""
    code = str(fm.feature_names[feature_idx])
    if code.startswith(("60", "68", "51", "52", "53")):
        return "SH"
    if code.startswith(("00", "30", "39", "12", "08")):
        return "SZ"
    if code.startswith(("8", "4", "43")):
        return "BJ"
    if len(code) == 5:
        return "HK"
    return "UNKNOWN"


def build_profiles(
    fm: FeatureMatrix,
    result: KMeansResult,
    mapping: IndustryMapping | None = None,
    top_n_holdings: int = 10,
    top_n_industries: int = 5,
    max_representatives: int = 5,
) -> list[ClusterProfile]:
    """Build a profile for each cluster.

    Args:
        fm: FeatureMatrix with weight matrix and metadata.
        result: KMeansResult with labels and centroids.
        mapping: Industry mapping for deriving industries from asset clusters.
        top_n_holdings: Number of top representative holdings to report.
        top_n_industries: Number of top industries to report.
        max_representatives: Number of representative products to list.

    Returns:
        List of ClusterProfile objects.
    """
    labels = result.labels
    k = result.centroids.shape[0]
    profiles: list[ClusterProfile] = []

    for cid in range(k):
        mask = labels == cid
        idx = np.where(mask)[0]
        size = int(mask.sum())
        X_c = fm.X[mask]
        centroid = result.centroids[cid]

        if fm.feature_type == "industry":
            top_industries = [
                {"industry": str(fm.feature_names[i]), "weight": float(centroid[i])}
                for i in np.argsort(centroid)[-top_n_industries:][::-1]
                if centroid[i] > 0
            ]
            top_holdings = [
                {"asset_code": item["industry"], "weight": item["weight"]}
                for item in top_industries[:top_n_holdings]
            ]
        else:
            top_holdings = [
                {"asset_code": str(fm.feature_names[i]), "weight": float(centroid[i])}
                for i in np.argsort(centroid)[-top_n_holdings:][::-1]
                if centroid[i] > 0
            ]
            if mapping is not None:
                top_industries = _derive_top_industries_from_assets(
                    fm, centroid, mapping, top_n_industries
                )
            else:
                top_industries = [
                    {"industry": f"asset:{h['asset_code']}", "weight": h["weight"]}
                    for h in top_holdings[:top_n_industries]
                ]

        # Concentration (use raw weights, not normalized vectors).
        raw_c = fm.raw_weights[mask]
        hhi_values = [compute_hhi(raw_c[i]) for i in range(size)]
        avg_hhi = float(np.mean(hhi_values)) if hhi_values else 0.0

        # Pairwise overlap.  avg_overlap uses the normalized vectors that were
        # fed into K-Means; avg_overlap_raw uses the original portfolio weights
        # and is closer to the business intuition of "common holdings".
        avg_overlap = _overlap_pairwise(X_c)
        avg_overlap_raw = _overlap_pairwise(raw_c)

        # Institution distribution.
        inst_counts = Counter(fm.institution_codes[mask])

        # AC share dominance: how many original products were collapsed into the
        # kept products of this cluster.  Ratio > 0 means some products in the
        # cluster are share-class duplicates of each other.
        total_merged = sum(
            len(
                fm.merge_map.get(
                    int(fm.product_ids[i]), [int(fm.product_ids[i])]
                )
            )
            for i in idx
        )
        ac_share_dominance_ratio = (
            float(total_merged - size) / size if size > 0 else 0.0
        )

        # Representatives: products closest to centroid.
        dist_to_center = np.linalg.norm(X_c - centroid, axis=1)
        rep_order = np.argsort(dist_to_center)
        n_rep = min(max_representatives, size)
        rep_local = rep_order[:n_rep]
        rep_global = idx[rep_local]

        cluster_label = derive_cluster_label(top_industries)

        profiles.append(
            ClusterProfile(
                cluster_id=cid,
                size=size,
                cluster_label=cluster_label,
                top_holdings=top_holdings,
                top_industries=top_industries,
                avg_hhi=avg_hhi,
                avg_overlap=avg_overlap,
                avg_overlap_raw=avg_overlap_raw,
                ac_share_dominance_ratio=ac_share_dominance_ratio,
                institution_distribution=dict(inst_counts),
                representative_products=[int(fm.product_ids[i]) for i in rep_global],
                representative_codes=[str(fm.product_codes[i]) for i in rep_global],
                representative_names=[str(fm.product_names[i]) for i in rep_global],
            )
        )

    return profiles
