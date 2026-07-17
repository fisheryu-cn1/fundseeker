#!/usr/bin/env python3
"""Migrate legacy similarity_cluster / similarity_cluster_member data.

The first-phase implementation stored a bogus ``cluster_run_id`` (the id of the
first cluster in the run).  This script creates proper ``similarity_cluster_run``
batches from the legacy data and rewrites the cluster/member records into the
new ``similarity_clusters`` / ``similarity_cluster_members`` tables.

Run after ``scripts/init_db.py`` has created the new tables.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text

from fundseeker.models.database import get_engine, get_session_maker
from fundseeker.models.tables import (
    SimilarityCluster,
    SimilarityClusterMember,
    SimilarityClusterRun,
)


def _parse_json(value: str | None) -> dict | list | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def migrate() -> None:
    engine = get_engine()
    Session = get_session_maker(engine)

    with engine.connect() as conn:
        groups = conn.execute(
            text(
                """
                SELECT DISTINCT report_date, algorithm, k, product_type_filter
                FROM similarity_cluster
                ORDER BY report_date, algorithm, k
                """
            )
        ).fetchall()

    print(f"Found {len(groups)} legacy run groups to migrate.")

    with Session() as session:
        for report_date, algorithm, k, product_type_filter in groups:
            # The legacy run is identified by the first cluster (cluster_id=0).
            first_cluster = session.execute(
                text(
                    """
                    SELECT id FROM similarity_cluster
                    WHERE report_date = :rd AND algorithm = :algo AND k = :k
                      AND cluster_id = 0
                    LIMIT 1
                    """
                ),
                {"rd": report_date, "algo": algorithm, "k": k},
            ).fetchone()
            if first_cluster is None:
                print(
                    f"  Skip: no cluster_id=0 for {report_date}/{algorithm}/k={k}"
                )
                continue
            legacy_run_marker = first_cluster.id

            clusters = session.execute(
                text(
                    """
                    SELECT * FROM similarity_cluster
                    WHERE report_date = :rd AND algorithm = :algo AND k = :k
                    ORDER BY cluster_id
                    """
                ),
                {"rd": report_date, "algo": algorithm, "k": k},
            ).mappings().all()

            members = session.execute(
                text(
                    """
                    SELECT * FROM similarity_cluster_member
                    WHERE cluster_run_id = :run_marker
                    ORDER BY product_id
                    """
                ),
                {"run_marker": legacy_run_marker},
            ).mappings().all()

            if not clusters or not members:
                print(f"  Skip empty run: {report_date}/{algorithm}/k={k}")
                continue

            run = SimilarityClusterRun(
                report_date=report_date,
                product_type_filter=product_type_filter,
                algorithm=algorithm,
                k=k,
                params_json={},
                silhouette=None,
                inertia=None,
                n_products=len({m["product_id"] for m in members}),
                n_features=None,
            )
            session.add(run)
            session.flush()

            cluster_id_map: dict[int, int] = {}
            for c in clusters:
                new_cluster = SimilarityCluster(
                    cluster_run_id=run.id,
                    report_date=c["report_date"],
                    product_type_filter=c["product_type_filter"],
                    algorithm=c["algorithm"],
                    k=c["k"],
                    cluster_id=c["cluster_id"],
                    cluster_label=c["cluster_label"],
                    size=c["size"],
                    top_industries=_parse_json(c["top_industries"]),
                    top_holdings=_parse_json(c["top_holdings"]),
                    avg_hhi=c["avg_hhi"],
                    avg_overlap=c["avg_overlap"],
                    avg_overlap_raw=None,
                    ac_share_dominance_ratio=None,
                    institution_distribution=_parse_json(c["institution_distribution"]),
                    representative_products=_parse_json(c["representative_products"]),
                    representative_codes=_parse_json(c["representative_codes"]),
                    representative_names=_parse_json(c["representative_names"]),
                    created_at=c["created_at"],
                )
                session.add(new_cluster)
                cluster_id_map[c["cluster_id"]] = c["cluster_id"]

            for m in members:
                session.add(
                    SimilarityClusterMember(
                        report_date=m["report_date"],
                        cluster_run_id=run.id,
                        product_id=m["product_id"],
                        cluster_id=m["cluster_id"],
                        distance_to_center=m["distance_to_center"],
                        created_at=m["created_at"],
                    )
                )

            session.commit()
            print(
                f"  Migrated run_id={run.id}: {report_date}/{algorithm}/k={k} "
                f"clusters={len(clusters)} members={len(members)}"
            )

    print("Migration complete.")


if __name__ == "__main__":
    migrate()
