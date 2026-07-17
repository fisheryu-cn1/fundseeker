#!/usr/bin/env python3
"""Initialize FundSeeker database tables."""

import sys
from pathlib import Path

# Make src/ importable when running directly.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from fundseeker.models.database import get_engine
from fundseeker.models.tables import Base


def init_db():
    engine = get_engine()
    print(f"Creating tables in: {engine.url}")
    Base.metadata.create_all(engine)
    print("All tables created successfully.")


if __name__ == "__main__":
    init_db()
