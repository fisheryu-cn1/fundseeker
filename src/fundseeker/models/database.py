"""Database connection helpers.

The default URL below is a generic placeholder. To use a custom connection
string for your local environment, either:

1. Set the ``FUNDSEEKER_DATABASE_URL`` environment variable, or
2. Create ``src/fundseeker/models/database_local.py`` (gitignored) and define
   ``DEFAULT_DB_URL`` there. This file will be imported automatically.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DEFAULT_DB_URL = (
    "postgresql+psycopg2://user:password@localhost:5432/fundseeker"
)

# Allow local override via database_local.py (not committed).
try:
    from fundseeker.models.database_local import DEFAULT_DB_URL as _LOCAL_DB_URL

    DEFAULT_DB_URL = _LOCAL_DB_URL
except ImportError:
    pass


def get_engine():
    """Create a SQLAlchemy engine using environment variables or defaults."""
    url = os.getenv("FUNDSEEKER_DATABASE_URL", DEFAULT_DB_URL)
    return create_engine(url, echo=False, future=True)


def get_session_maker(engine=None):
    """Return a configured session maker."""
    if engine is None:
        engine = get_engine()
    return sessionmaker(bind=engine, future=True)
