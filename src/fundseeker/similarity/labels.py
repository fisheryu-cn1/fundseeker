"""Cluster label derivation from top industries.

This module is intentionally kept separate from the web layer so that the
similarity service can persist human-readable cluster labels at write time,
while the web UI can still fall back to the same rule when reading old runs
that were stored before the label was populated.
"""

from __future__ import annotations

from typing import Any


# Generic 2-char suffixes that should be dropped from a derived industry name
# to make the title cleaner. E.g. "白酒Ⅱ" -> "白酒", "银行Ⅱ" -> "银行".
_CLUSTER_LABEL_SUFFIXES = ("Ⅱ", "III", "II", "I", "1", "2", "3")


def _shorten_industry(name: str) -> str:
    """Trim roman-numeral / numeric suffixes from an industry name."""
    cleaned = (name or "").strip()
    for suf in _CLUSTER_LABEL_SUFFIXES:
        if cleaned.endswith(suf):
            cleaned = cleaned[: -len(suf)].rstrip()
            break
    return cleaned or name


def derive_cluster_label(
    top_industries: list[dict[str, Any]],
    *,
    max_pieces: int = 3,
    min_weight: float = 0.05,
) -> str | None:
    """Derive a human-readable cluster label from its top industries.

    The label concatenates the most representative industry names with ``" + "``
    so the cluster's investment theme is obvious at a glance, e.g.
    ``"通信 + 半导体"`` or ``"白酒 + 家电 + 消费"``.

    Args:
        top_industries: ``[{"industry": str, "weight": float}, ...]`` from a
            cluster profile (already ordered by weight desc).
        max_pieces: maximum number of industries to concatenate.
        min_weight: industries with weight below this share are dropped from
            the label even if there are fewer than ``max_pieces`` survivors;
            this keeps the label focused on the dominant theme.

    Returns:
        The composed label, or ``None`` when no usable industry is found.
    """
    pieces: list[str] = []
    seen: set[str] = set()
    for ind in top_industries or []:
        name = ind.get("industry") if isinstance(ind, dict) else None
        weight = float(ind.get("weight") or 0.0) if isinstance(ind, dict) else 0.0
        if not name or name == "未知行业":
            continue
        if weight < min_weight:
            continue
        short = _shorten_industry(name)
        if short in seen:
            continue
        seen.add(short)
        pieces.append(short)
        if len(pieces) >= max_pieces:
            break
    if not pieces:
        return None
    return " + ".join(pieces)
