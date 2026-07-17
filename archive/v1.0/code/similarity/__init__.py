"""FundSeeker similarity analysis service.

This package provides clustering, pairwise similarity, attribution and
shift-analysis capabilities based on portfolio holdings. It is designed to be
independent from the data-collection pipeline and callable via CLI or Python API.
"""

from __future__ import annotations

from fundseeker.similarity.service import SimilarityService

__all__ = ["SimilarityService"]
