"""Baseline persistence and incremental clustering decision logic."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import select

from fundseeker.models.database import get_session_maker
from fundseeker.models.tables import SimilarityClusterBaseline
from fundseeker.similarity.clustering import KMeansResult
from fundseeker.similarity.config import IncrementalConfig
from fundseeker.similarity.features import FeatureMatrix


@dataclass
class ClusterBaseline:
    """In-memory representation of a clustering baseline."""

    cluster_run_id: int
    report_date: date
    product_type_filter: str | None
    algorithm: str
    k: int
    feature_type: str
    feature_names: list[str]
    centroids: np.ndarray
    silhouette: float | None
    inertia: float | None
    n_products: int
    k_search_results: list[dict[str, Any]] | None = None

    @property
    def baseline_key(self) -> tuple[str, str | None, str]:
        return (self.algorithm, self.product_type_filter, self.feature_type)


def _json_or_none(value: Any) -> Any:
    """Handle legacy text JSON or native JSONB."""
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def load_baseline(
    algorithm: str,
    product_type_filter: str | None,
    feature_type: str,
) -> ClusterBaseline | None:
    """Load the most recent baseline for a given algorithm/feature combo."""
    Session = get_session_maker()
    with Session() as session:
        query = (
            select(SimilarityClusterBaseline)
            .where(
                SimilarityClusterBaseline.algorithm == algorithm,
                SimilarityClusterBaseline.feature_type == feature_type,
            )
            .order_by(SimilarityClusterBaseline.created_at.desc())
        )
        if product_type_filter is not None:
            query = query.where(
                SimilarityClusterBaseline.product_type_filter == product_type_filter
            )
        else:
            query = query.where(
                SimilarityClusterBaseline.product_type_filter.is_(None)
            )

        record = session.scalars(query).first()
        if record is None:
            return None

        return ClusterBaseline(
            cluster_run_id=record.cluster_run_id,
            report_date=record.report_date,
            product_type_filter=record.product_type_filter,
            algorithm=record.algorithm,
            k=record.k,
            feature_type=record.feature_type,
            feature_names=list(_json_or_none(record.feature_names) or []),
            centroids=np.array(_json_or_none(record.centroids), dtype=np.float64),
            silhouette=(
                float(record.silhouette) if record.silhouette is not None else None
            ),
            inertia=float(record.inertia) if record.inertia is not None else None,
            n_products=record.n_products,
            k_search_results=_json_or_none(record.k_search_results),
        )


def save_baseline(
    cluster_run_id: int,
    report_date: date,
    product_type_filter: str | None,
    algorithm: str,
    k: int,
    feature_type: str,
    fm: FeatureMatrix,
    result: KMeansResult,
    k_search_results: list[dict[str, Any]] | None,
) -> int:
    """Persist a new baseline, replacing any existing one for the same key."""
    from sqlalchemy import delete

    Session = get_session_maker()
    with Session() as session:
        # Use a direct DELETE statement so the replacement is guaranteed to
        # happen before the INSERT and avoids stale-object ordering issues.
        delete_filter = [
            SimilarityClusterBaseline.algorithm == algorithm,
            SimilarityClusterBaseline.feature_type == feature_type,
        ]
        if product_type_filter is not None:
            delete_filter.append(
                SimilarityClusterBaseline.product_type_filter == product_type_filter
            )
        else:
            delete_filter.append(SimilarityClusterBaseline.product_type_filter.is_(None))
        session.execute(delete(SimilarityClusterBaseline).where(*delete_filter))

        record = SimilarityClusterBaseline(
            cluster_run_id=cluster_run_id,
            report_date=report_date,
            product_type_filter=product_type_filter,
            algorithm=algorithm,
            k=k,
            feature_type=feature_type,
            feature_names=list(fm.feature_names),
            centroids=result.centroids.tolist(),
            silhouette=result.silhouette,
            inertia=result.inertia,
            n_products=fm.n_products,
            k_search_results=k_search_results,
        )
        session.add(record)
        session.flush()
        baseline_id = record.id
        session.commit()
    return baseline_id


def align_centroids(
    baseline: ClusterBaseline,
    fm: FeatureMatrix,
) -> np.ndarray:
    """Align baseline centroids to the feature space of ``fm``.

    Returns a (k, n_features) centroid matrix whose columns correspond to
    ``fm.feature_names``.  Missing features are filled with 0; features that
    existed in the baseline but not in the new matrix are dropped.
    """
    old_names = baseline.feature_names
    new_names = list(fm.feature_names)
    old_index = {name: i for i, name in enumerate(old_names)}

    aligned = np.zeros((baseline.k, fm.n_features), dtype=np.float64)
    for j, name in enumerate(new_names):
        if name in old_index:
            aligned[:, j] = baseline.centroids[:, old_index[name]]
    return aligned


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def should_fall_back_to_full(
    baseline: ClusterBaseline,
    fm: FeatureMatrix,
    result: KMeansResult,
    cfg: IncrementalConfig,
) -> tuple[bool, dict[str, Any]]:
    """Decide whether an incremental result has degraded enough to require full recompute.

    Returns:
        (fallback_needed, diagnostics)
    """
    diagnostics: dict[str, Any] = {
        "baseline_run_id": baseline.cluster_run_id,
        "baseline_n_products": baseline.n_products,
        "baseline_silhouette": baseline.silhouette,
        "baseline_inertia": baseline.inertia,
        "current_n_products": fm.n_products,
        "current_silhouette": result.silhouette,
        "current_inertia": result.inertia,
        "checks": {},
    }

    checks = diagnostics["checks"]

    # Baseline completeness guard: if the baseline run lacks essential metrics,
    # treat it as untrustworthy and force a full recompute.
    baseline_complete = (
        baseline.silhouette is not None and baseline.inertia is not None
    )
    diagnostics["baseline_complete"] = baseline_complete

    # 1. Feature space stability.
    feature_jaccard = _jaccard_similarity(
        set(baseline.feature_names), set(fm.feature_names)
    )
    checks["feature_jaccard"] = {
        "value": feature_jaccard,
        "threshold": cfg.feature_jaccard_min,
        "violated": feature_jaccard < cfg.feature_jaccard_min,
    }

    # 2. Product coverage stability.
    n_change = abs(fm.n_products - baseline.n_products) / max(baseline.n_products, 1)
    checks["n_products_change_ratio"] = {
        "value": n_change,
        "threshold": cfg.n_products_change_ratio,
        "violated": n_change > cfg.n_products_change_ratio,
    }

    # 3. Silhouette absolute floor.
    current_sil = result.silhouette if result.silhouette is not None else -1.0
    base_sil = baseline.silhouette if baseline.silhouette is not None else None
    checks["silhouette_min"] = {
        "value": current_sil,
        "threshold": cfg.silhouette_min,
        "violated": current_sil < cfg.silhouette_min,
    }

    # 4. Silhouette drop vs baseline.
    silhouette_drop = None
    if base_sil is not None and base_sil != 0:
        silhouette_drop = (base_sil - current_sil) / abs(base_sil)
        checks["silhouette_drop_ratio"] = {
            "value": silhouette_drop,
            "threshold": cfg.silhouette_drop_ratio,
            "violated": silhouette_drop > cfg.silhouette_drop_ratio,
        }
    else:
        checks["silhouette_drop_ratio"] = {
            "value": None,
            "threshold": cfg.silhouette_drop_ratio,
            "violated": False,
        }

    # 5. Inertia change vs baseline.
    inertia_change = None
    if baseline.inertia is not None and baseline.inertia > 0:
        inertia_change = abs(result.inertia - baseline.inertia) / baseline.inertia
        checks["inertia_change_ratio"] = {
            "value": inertia_change,
            "threshold": cfg.inertia_change_ratio,
            "violated": inertia_change > cfg.inertia_change_ratio,
        }
    else:
        checks["inertia_change_ratio"] = {
            "value": None,
            "threshold": cfg.inertia_change_ratio,
            "violated": False,
        }

    fallback_needed = (
        any(c["violated"] for c in checks.values()) or not baseline_complete
    )
    diagnostics["fallback_needed"] = fallback_needed
    if not baseline_complete:
        diagnostics["fallback_reason"] = "baseline_metrics_incomplete"
    return fallback_needed, diagnostics
