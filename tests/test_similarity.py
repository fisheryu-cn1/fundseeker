"""Unit tests for the similarity clustering package."""

from __future__ import annotations

import numpy as np
import pytest

from fundseeker.similarity.baseline import (
    ClusterBaseline,
    align_centroids,
    should_fall_back_to_full,
)
from fundseeker.similarity.clustering import (
    compute_silhouette,
    kmeans,
    kmeans_from_centroids,
    select_k_elbow,
)
from fundseeker.similarity.config import IncrementalConfig
from fundseeker.similarity.features import FeatureMatrix


def _dummy_fm(X: np.ndarray, feature_names: list[str] | None = None) -> FeatureMatrix:
    n_samples, n_features = X.shape
    names = feature_names or [f"f{i}" for i in range(n_features)]
    return FeatureMatrix(
        X=X,
        raw_weights=X.copy(),
        product_ids=np.arange(n_samples),
        product_codes=np.array([f"p{i}" for i in range(n_samples)]),
        product_names=np.array([f"Product {i}" for i in range(n_samples)]),
        institution_codes=np.array(["IC"]*n_samples),
        product_types=np.array(["equity"] * n_samples),
        feature_names=np.array(names),
        feature_type="asset",
        report_date="2026-03-31",
    )


def test_kmeans_from_centroids_reuses_centroids():
    rng = np.random.default_rng(42)
    # Three well-separated blobs.
    centers = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]])
    X = np.vstack(
        [rng.normal(loc=c, scale=0.5, size=(30, 2)) for c in centers]
    )

    full = kmeans(X, k=3, seed=42)
    warm = kmeans_from_centroids(X, centroids=full.centroids, max_iter=10, tol=1e-4)

    assert warm.labels.shape == (X.shape[0],)
    assert warm.centroids.shape == (3, 2)
    # With the same initialization, warm-start should converge in one iteration.
    assert warm.n_iter <= 2
    np.testing.assert_allclose(warm.inertia, full.inertia, rtol=1e-3)


def test_select_k_elbow_returns_valid_k():
    rng = np.random.default_rng(7)
    centers = np.array([[0.0, 0.0], [5.0, 0.0], [0.0, 5.0], [5.0, 5.0]])
    X = np.vstack(
        [rng.normal(loc=c, scale=0.4, size=(40, 2)) for c in centers]
    )

    selection = select_k_elbow(
        X,
        k_min=2,
        k_max=6,
        elbow_weight=0.3,
        seed=42,
    )
    assert 2 <= selection["best_k"] <= 6
    assert selection["best_result"] is not None
    assert len(selection["results"]) == 5
    assert selection["selection_method"] == "silhouette_elbow_composite"


def test_align_centroids_handles_feature_mismatch():
    old_names = ["a", "b", "c"]
    new_names = ["b", "c", "d"]
    centroids = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    baseline = ClusterBaseline(
        cluster_run_id=1,
        report_date="2026-03-31",
        product_type_filter="equity,mixed",
        algorithm="kmeans-asset",
        k=2,
        feature_type="asset",
        feature_names=old_names,
        centroids=centroids,
        silhouette=0.1,
        inertia=100.0,
        n_products=10,
    )
    X = np.zeros((10, 4))
    fm = _dummy_fm(X, feature_names=new_names)

    aligned = align_centroids(baseline, fm)
    assert aligned.shape == (2, 4)
    # "b" and "c" columns should carry over values.
    np.testing.assert_allclose(aligned[:, 0], [2.0, 5.0])
    np.testing.assert_allclose(aligned[:, 1], [3.0, 6.0])
    # "d" column should be zero-filled.
    np.testing.assert_allclose(aligned[:, 3], [0.0, 0.0])


def test_should_fall_back_to_full_triggers_on_bad_silhouette():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(50, 4))
    result = kmeans(X, k=3, seed=42)
    result.silhouette = compute_silhouette(X, result.labels)

    baseline = ClusterBaseline(
        cluster_run_id=1,
        report_date="2026-03-31",
        product_type_filter="equity,mixed",
        algorithm="kmeans-asset",
        k=3,
        feature_type="asset",
        feature_names=["f0", "f1", "f2", "f3"],
        centroids=result.centroids.copy(),
        silhouette=0.5,
        inertia=10.0,
        n_products=50,
    )
    cfg = IncrementalConfig(
        silhouette_min=0.999,  # Impossibly high.
        silhouette_drop_ratio=0.0,
        inertia_change_ratio=1.0,
        n_products_change_ratio=1.0,
        feature_jaccard_min=0.0,
    )
    fm = _dummy_fm(X, feature_names=["f0", "f1", "f2", "f3"])

    fallback, diagnostics = should_fall_back_to_full(baseline, fm, result, cfg)
    assert fallback is True
    assert diagnostics["checks"]["silhouette_min"]["violated"] is True


def test_should_fall_back_to_full_passes_on_stable_data():
    rng = np.random.default_rng(2)
    centers = np.array([[0.0, 0.0], [5.0, 0.0]])
    X = np.vstack(
        [rng.normal(loc=c, scale=0.5, size=(30, 2)) for c in centers]
    )
    result = kmeans(X, k=2, seed=42)
    result.silhouette = compute_silhouette(X, result.labels)

    baseline = ClusterBaseline(
        cluster_run_id=1,
        report_date="2026-03-31",
        product_type_filter="equity,mixed",
        algorithm="kmeans-asset",
        k=2,
        feature_type="asset",
        feature_names=["f0", "f1"],
        centroids=result.centroids.copy(),
        silhouette=result.silhouette,
        inertia=result.inertia,
        n_products=X.shape[0],
    )
    cfg = IncrementalConfig()
    fm = _dummy_fm(X, feature_names=["f0", "f1"])

    fallback, diagnostics = should_fall_back_to_full(baseline, fm, result, cfg)
    assert fallback is False
    assert diagnostics["checks"]["feature_jaccard"]["value"] == 1.0
