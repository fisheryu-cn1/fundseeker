"""Integration tests for the incremental clustering service path."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest import mock

import numpy as np
import pytest

from sqlalchemy import select, update

from fundseeker.models.database import get_engine, get_session_maker
from fundseeker.models.tables import (
    ProductInfo,
    SimilarityClusterBaseline,
    SimilarityClusterRun,
)
from fundseeker.similarity.config import SimilarityConfig
from fundseeker.similarity.features import FeatureMatrix
from fundseeker.similarity.service import SimilarityService


_TEST_DATE = date(2099, 1, 1)


def _dummy_fm(seed: int = 1, n_samples: int = 60, n_features: int = 8) -> FeatureMatrix:
    rng = np.random.default_rng(seed)
    # Three well-separated blobs so K-Means is stable.
    centers = np.array([[0.0, 0.0], [5.0, 0.0], [0.0, 5.0]])
    X = np.vstack(
        [rng.normal(loc=c, scale=0.5, size=(n_samples // 3, 2)) for c in centers]
    )
    # Pad to requested feature count.
    if n_features > 2:
        X = np.concatenate(
            [X, rng.normal(size=(X.shape[0], n_features - 2))],
            axis=1,
        )
    return FeatureMatrix(
        X=X,
        raw_weights=X.copy(),
        product_ids=np.arange(X.shape[0]),
        product_codes=np.array([f"p{i}" for i in range(X.shape[0])]),
        product_names=np.array([f"Product {i}" for i in range(X.shape[0])]),
        institution_codes=np.array(["TST"] * X.shape[0]),
        product_types=np.array(["equity"] * X.shape[0]),
        feature_names=np.array([f"f{i}" for i in range(n_features)]),
        feature_type="asset",
        report_date=_TEST_DATE,
    )


def _cleanup_test_data() -> None:
    """Remove all test records created for the integration date."""
    engine = get_engine()
    Session = get_session_maker(engine)
    with Session() as session:
        # Break self-references between runs before deleting.
        session.execute(
            update(SimilarityClusterRun)
            .where(SimilarityClusterRun.report_date == _TEST_DATE)
            .values(baseline_run_id=None)
        )
        runs = session.scalars(
            select(SimilarityClusterRun).where(
                SimilarityClusterRun.report_date == _TEST_DATE
            )
        ).all()
        for run in runs:
            session.delete(run)
        baselines = session.scalars(
            select(SimilarityClusterBaseline).where(
                SimilarityClusterBaseline.report_date == _TEST_DATE
            )
        ).all()
        for baseline in baselines:
            session.delete(baseline)
        # Delete products inserted for tests.  Cluster members are removed by
        # cascading deletes on similarity_cluster_run.
        products = session.scalars(
            select(ProductInfo).where(ProductInfo.product_code.like("TST-%"))
        ).all()
        for product in products:
            session.delete(product)
        session.commit()


def _ensure_test_products(product_ids: np.ndarray) -> None:
    """Insert placeholder ProductInfo rows so member FK constraints pass."""
    Session = get_session_maker()
    with Session() as session:
        existing = {
            row[0]
            for row in session.execute(select(ProductInfo.id)).all()
        }
        for pid in product_ids:
            pid_int = int(pid)
            if pid_int in existing:
                continue
            session.add(
                ProductInfo(
                    id=pid_int,
                    institution_type="fund_company",
                    institution_name="Test Institution",
                    institution_code="TST",
                    product_code=f"TST-{pid_int:06d}",
                    product_name=f"Test Product {pid_int}",
                    product_type="equity",
                    risk_level="R3",
                    risk_level_standard="L3",
                    currency="CNY",
                    manager="Test Manager",
                    data_source="test",
                    collect_date=datetime.now(),
                )
            )
        session.commit()


@pytest.fixture(autouse=True)
def _clean_before_and_after():
    _cleanup_test_data()
    yield
    _cleanup_test_data()


def _service_with_mock_fm(fm: FeatureMatrix, config: SimilarityConfig | None = None):
    _ensure_test_products(fm.product_ids)
    svc = SimilarityService(config=config)
    svc.build_features = mock.Mock(return_value=fm)  # type: ignore[assignment]
    return svc


def test_auto_first_run_creates_baseline():
    fm = _dummy_fm()
    svc = _service_with_mock_fm(fm)

    result = svc.cluster(
        report_date=_TEST_DATE,
        product_types=("equity",),
        k="auto",
        feature_type="asset",
        mode="auto",
    )

    assert result["mode"] == "full"
    assert result["cluster_run_id"] is not None
    assert result["baseline_run_id"] is None
    assert result["k_search_results"] is not None
    assert result["k"] == 3  # three blobs

    Session = get_session_maker()
    with Session() as session:
        baseline = session.scalars(
            select(SimilarityClusterBaseline).where(
                SimilarityClusterBaseline.report_date == _TEST_DATE,
                SimilarityClusterBaseline.algorithm == "kmeans-asset",
            )
        ).first()
        assert baseline is not None
        assert baseline.k == result["k"]


def test_auto_second_run_uses_incremental():
    fm = _dummy_fm()
    svc = _service_with_mock_fm(fm)

    first = svc.cluster(
        report_date=_TEST_DATE,
        product_types=("equity",),
        k="auto",
        feature_type="asset",
        mode="auto",
    )
    second = svc.cluster(
        report_date=_TEST_DATE,
        product_types=("equity",),
        k="auto",
        feature_type="asset",
        mode="auto",
    )

    assert first["mode"] == "full"
    assert second["mode"] == "incremental"
    assert second["baseline_run_id"] == first["cluster_run_id"]
    assert second["k"] == first["k"]
    diagnostics = second.get("incremental_diagnostics")
    assert diagnostics is not None
    assert diagnostics["fallback_needed"] is False


def test_incremental_without_baseline_raises():
    fm = _dummy_fm()
    svc = _service_with_mock_fm(fm)

    with pytest.raises(ValueError, match="No baseline found"):
        svc.cluster(
            report_date=_TEST_DATE,
            product_types=("equity",),
            k="auto",
            feature_type="asset",
            mode="incremental",
        )


def test_auto_fallback_on_degraded_data():
    fm = _dummy_fm(seed=42)
    svc = _service_with_mock_fm(fm)

    first = svc.cluster(
        report_date=_TEST_DATE,
        product_types=("equity",),
        k="auto",
        feature_type="asset",
        mode="auto",
    )

    # Tighten thresholds to force a fallback on the second run.
    cfg = SimilarityConfig()
    cfg.incremental.silhouette_min = 0.999
    svc2 = _service_with_mock_fm(fm, config=cfg)

    second = svc2.cluster(
        report_date=_TEST_DATE,
        product_types=("equity",),
        k="auto",
        feature_type="asset",
        mode="auto",
    )

    assert first["mode"] == "full"
    assert second["mode"] == "full"
    assert second["cluster_run_id"] != first["cluster_run_id"]
    diagnostics = second.get("incremental_diagnostics")
    assert diagnostics is not None
    assert diagnostics["fallback_needed"] is True
    assert diagnostics["checks"]["silhouette_min"]["violated"] is True


def test_incremental_mode_raises_on_degraded_data():
    fm = _dummy_fm(seed=42)
    svc = _service_with_mock_fm(fm)

    svc.cluster(
        report_date=_TEST_DATE,
        product_types=("equity",),
        k="auto",
        feature_type="asset",
        mode="full",
    )

    cfg = SimilarityConfig()
    cfg.incremental.silhouette_min = 0.999
    svc2 = _service_with_mock_fm(fm, config=cfg)

    with pytest.raises(RuntimeError, match="Incremental clustering quality check failed"):
        svc2.cluster(
            report_date=_TEST_DATE,
            product_types=("equity",),
            k="auto",
            feature_type="asset",
            mode="incremental",
        )
