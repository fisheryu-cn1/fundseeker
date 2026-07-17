#!/usr/bin/env python3
"""Drop legacy singular-name similarity tables after migration.

Run ``scripts/migrate_similarity_phase1.py`` first and verify that the new
plural-name tables contain the expected data.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import text

from fundseeker.models.database import get_engine


LEGACY_TABLES = [
    "similarity_cluster",
    "similarity_cluster_member",
]


def drop_legacy_tables() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        for table in LEGACY_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            print(f"Dropped legacy table: {table}")
        conn.commit()
    print("Legacy tables cleanup complete.")


if __name__ == "__main__":
    drop_legacy_tables()
