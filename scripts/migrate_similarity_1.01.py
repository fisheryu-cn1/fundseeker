#!/usr/bin/env python3
"""Migrate similarity schema for v1.01 incremental clustering.

Adds:
  - similarity_cluster_baseline table
  - similarity_cluster_run.mode column
  - similarity_cluster_run.baseline_run_id column

Run after updating the codebase to v1.01.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text

from fundseeker.models.database import get_engine


MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS similarity_cluster_baseline (
    id BIGSERIAL PRIMARY KEY,
    cluster_run_id BIGINT NOT NULL REFERENCES similarity_cluster_run(id) ON DELETE CASCADE,
    report_date DATE NOT NULL,
    product_type_filter VARCHAR(100),
    algorithm VARCHAR(30) NOT NULL,
    k INTEGER NOT NULL,
    feature_type VARCHAR(20) NOT NULL,
    feature_names JSONB NOT NULL,
    centroids JSONB NOT NULL,
    silhouette NUMERIC(10, 6),
    inertia NUMERIC(20, 6),
    n_products INTEGER NOT NULL,
    k_search_results JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uix_similarity_cluster_baseline
        UNIQUE (report_date, product_type_filter, algorithm)
);

CREATE INDEX IF NOT EXISTS ix_similarity_cluster_baseline_run
    ON similarity_cluster_baseline(cluster_run_id);
CREATE INDEX IF NOT EXISTS ix_similarity_cluster_baseline_lookup
    ON similarity_cluster_baseline(report_date, product_type_filter, algorithm);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'similarity_cluster_run' AND column_name = 'mode'
    ) THEN
        ALTER TABLE similarity_cluster_run
        ADD COLUMN mode VARCHAR(20) NOT NULL DEFAULT 'full';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'similarity_cluster_run'
          AND column_name = 'baseline_run_id'
    ) THEN
        ALTER TABLE similarity_cluster_run
        ADD COLUMN baseline_run_id BIGINT REFERENCES similarity_cluster_run(id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_similarity_cluster_run_baseline
    ON similarity_cluster_run(baseline_run_id);
"""


def migrate() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(MIGRATION_SQL))
    print("v1.01 similarity schema migration completed.")


if __name__ == "__main__":
    migrate()
