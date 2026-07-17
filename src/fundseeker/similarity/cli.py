"""Legacy module-level CLI entry point for portfolio similarity analysis.

.. deprecated::
    Use ``scripts/fundseeker_similarity.py`` instead.  This module is kept
    for backward compatibility and delegates all work to
    ``fundseeker.similarity.cli_core``.

Examples:
    PYTHONPATH=src python scripts/fundseeker_similarity.py cluster \
        --report-date 2026-03-31 --k auto

    PYTHONPATH=src python scripts/fundseeker_similarity.py cluster \
        --report-date 2026-03-31 --feature-type industry --k auto

    PYTHONPATH=src python scripts/fundseeker_similarity.py refresh-industries

    PYTHONPATH=src python scripts/fundseeker_similarity.py refresh-quotes \
        --report-date 2026-03-31 --start-date 2026-04-01 --end-date 2026-07-10

    PYTHONPATH=src python scripts/fundseeker_similarity.py attribution \
        --report-date 2026-03-31 --cluster-id 0 \
        --start-date 2026-04-01 --end-date 2026-07-10

    PYTHONPATH=src python scripts/fundseeker_similarity.py neighbors \
        --product-id 117661 --report-date 2026-03-31 --top-n 10

    PYTHONPATH=src python scripts/fundseeker_similarity.py list \
        --report-date 2026-03-31 --algorithm kmeans-industry
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root / "src"))

from fundseeker.similarity.cli_core import main as _core_main


def main(argv: list[str] | None = None) -> int:
    """Run the similarity CLI with a deprecation warning."""
    warnings.warn(
        "python -m fundseeker.similarity.cli is deprecated. "
        "Use PYTHONPATH=src python scripts/fundseeker_similarity.py instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _core_main(argv)


if __name__ == "__main__":
    sys.exit(main())
