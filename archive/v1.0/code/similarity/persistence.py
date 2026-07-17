"""Persistence helpers for similarity analysis results."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import delete, select

from fundseeker.models.database import get_session_maker
from fundseeker.models.tables import (
    SimilarityAttribution,
    SimilarityCluster,
    SimilarityClusterMember,
    SimilarityClusterRun,
)
from fundseeker.similarity.clustering import KMeansResult
from fundseeker.similarity.features import FeatureMatrix
from fundseeker.similarity.profiling import ClusterProfile


def save_cluster_run(
    report_date: date,
    product_type_filter: str | None,
    algorithm: str,
    k: int,
    params: dict[str, Any],
    fm: FeatureMatrix,
    result: KMeansResult,
    profiles: list[ClusterProfile],
) -> int:
    """Save a full cluster run to the database.

    Returns:
        The cluster_run_id used to group members.
    """
    Session = get_session_maker()

    with Session() as session:
        # Clean up previous run(s) with the same (report_date, algorithm, k,
        # product_type_filter). Cascading deletes remove clusters and members.
        prior_runs = session.scalars(
            select(SimilarityClusterRun).where(
                SimilarityClusterRun.report_date == report_date,
                SimilarityClusterRun.algorithm == algorithm,
                SimilarityClusterRun.k == k,
                SimilarityClusterRun.product_type_filter == product_type_filter,
            )
        ).all()
        for run in prior_runs:
            session.delete(run)
        session.flush()

        run = SimilarityClusterRun(
            report_date=report_date,
            product_type_filter=product_type_filter,
            algorithm=algorithm,
            k=k,
            params_json=params,
            silhouette=result.silhouette,
            inertia=result.inertia,
            n_products=fm.n_products,
            n_features=fm.n_features,
        )
        session.add(run)
        session.flush()

        for p in profiles:
            record = SimilarityCluster(
                cluster_run_id=run.id,
                report_date=report_date,
                product_type_filter=product_type_filter,
                algorithm=algorithm,
                k=k,
                cluster_id=p.cluster_id,
                cluster_label=p.cluster_label,
                size=p.size,
                top_industries=p.top_industries,
                top_holdings=p.top_holdings,
                avg_hhi=p.avg_hhi,
                avg_overlap=p.avg_overlap,
                avg_overlap_raw=p.avg_overlap_raw,
                ac_share_dominance_ratio=p.ac_share_dominance_ratio,
                institution_distribution=p.institution_distribution,
                representative_products=p.representative_products,
                representative_codes=p.representative_codes,
                representative_names=p.representative_names,
            )
            session.add(record)
        session.flush()

        # Insert members.
        for i in range(fm.n_products):
            cid = int(result.labels[i])
            dist = None
            if result.centroids is not None:
                dist = float(np.linalg.norm(fm.X[i] - result.centroids[cid]))
            member = SimilarityClusterMember(
                report_date=report_date,
                cluster_run_id=run.id,
                product_id=int(fm.product_ids[i]),
                cluster_id=cid,
                distance_to_center=dist,
            )
            session.add(member)

        session.commit()
        return run.id


def load_cluster_run(
    report_date: date,
    algorithm: str = "kmeans",
    k: int | None = None,
    product_type_filter: str | None = None,
) -> dict[str, Any]:
    """Load a cluster run from the database."""
    Session = get_session_maker()

    with Session() as session:
        query = select(SimilarityClusterRun).where(
            SimilarityClusterRun.report_date == report_date,
            SimilarityClusterRun.algorithm == algorithm,
        )
        if k is not None:
            query = query.where(SimilarityClusterRun.k == k)
        if product_type_filter is not None:
            query = query.where(
                SimilarityClusterRun.product_type_filter == product_type_filter
            )
        query = query.order_by(SimilarityClusterRun.created_at.desc())

        run = session.scalars(query).first()
        if run is None:
            raise ValueError(
                f"No cluster run found for report_date={report_date}, "
                f"algorithm={algorithm}, k={k}, product_type_filter={product_type_filter}"
            )

        clusters = session.scalars(
            select(SimilarityCluster).where(
                SimilarityCluster.cluster_run_id == run.id
            )
        ).all()
        members = session.scalars(
            select(SimilarityClusterMember).where(
                SimilarityClusterMember.cluster_run_id == run.id
            )
        ).all()

        return {
            "cluster_run_id": run.id,
            "report_date": report_date,
            "algorithm": algorithm,
            "k": run.k,
            "product_type_filter": run.product_type_filter,
            "params_json": run.params_json,
            "silhouette": float(run.silhouette) if run.silhouette is not None else None,
            "inertia": float(run.inertia) if run.inertia is not None else None,
            "n_products": run.n_products,
            "n_features": run.n_features,
            "created_at": run.created_at,
            "clusters": [
                {
                    "cluster_id": c.cluster_id,
                    "cluster_label": c.cluster_label,
                    "size": c.size,
                    "top_holdings": _load_json(c.top_holdings),
                    "top_industries": _load_json(c.top_industries),
                    "avg_hhi": float(c.avg_hhi) if c.avg_hhi is not None else None,
                    "avg_overlap": (
                        float(c.avg_overlap) if c.avg_overlap is not None else None
                    ),
                    "avg_overlap_raw": (
                        float(c.avg_overlap_raw)
                        if c.avg_overlap_raw is not None
                        else None
                    ),
                    "ac_share_dominance_ratio": (
                        float(c.ac_share_dominance_ratio)
                        if c.ac_share_dominance_ratio is not None
                        else None
                    ),
                    "institution_distribution": _load_json(c.institution_distribution),
                    "representative_products": _load_json(c.representative_products),
                    "representative_codes": _load_json(c.representative_codes),
                    "representative_names": _load_json(c.representative_names),
                }
                for c in clusters
            ],
            "members": [
                {
                    "product_id": m.product_id,
                    "cluster_id": m.cluster_id,
                    "distance_to_center": (
                        float(m.distance_to_center)
                        if m.distance_to_center is not None
                        else None
                    ),
                }
                for m in members
            ],
        }


def _load_json(value: Any) -> Any:
    """Load JSON value, handling both JSONB-native objects and legacy text."""
    if value is None:
        return None
    if isinstance(value, str):
        if not value:
            return None
        return json.loads(value)
    return value


def save_attribution(
    cluster_run_id: int,
    cluster_id: int,
    report_date: date,
    start_date: date,
    end_date: date,
    benchmark_type: str,
    benchmark_code: str | None,
    results: list[Any],
) -> int:
    """Persist Brinson attribution results.

    Existing records for the same (cluster_run_id, cluster_id, start_date,
    end_date, benchmark_type, benchmark_code) are replaced.
    """
    from fundseeker.similarity.attribution import AttributionResult

    Session = get_session_maker()
    with Session() as session:
        delete_filter = [
            SimilarityAttribution.cluster_run_id == cluster_run_id,
            SimilarityAttribution.cluster_id == cluster_id,
            SimilarityAttribution.start_date == start_date,
            SimilarityAttribution.end_date == end_date,
            SimilarityAttribution.benchmark_type == benchmark_type,
            SimilarityAttribution.benchmark_code.is_(None)
            if benchmark_code is None
            else SimilarityAttribution.benchmark_code == benchmark_code,
        ]
        session.execute(delete(SimilarityAttribution).where(*delete_filter))

        for r in results:
            if not isinstance(r, AttributionResult):
                continue
            session.add(
                SimilarityAttribution(
                    product_id=r.product_id,
                    cluster_run_id=cluster_run_id,
                    cluster_id=r.cluster_id,
                    report_date=report_date,
                    start_date=start_date,
                    end_date=end_date,
                    benchmark_type=benchmark_type,
                    benchmark_code=benchmark_code,
                    total_return=r.total_return,
                    benchmark_return=r.benchmark_return,
                    excess_return=r.excess_return,
                    allocation_effect=r.allocation_effect,
                    selection_effect=r.selection_effect,
                    interaction_effect=r.interaction_effect,
                    rank_in_cluster=r.rank_in_cluster,
                )
            )

        session.commit()
    return len(results)
