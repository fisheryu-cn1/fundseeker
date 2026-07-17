"""Feature engineering for portfolio similarity and clustering."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from fundseeker.similarity.data import HoldingData
from fundseeker.similarity.industry import IndustryMapping, build_industry_weights


# Regex for stripping trailing A/B/C/E/H share-class suffixes, with or without a
# leading space.  These letters are the standard mutual-fund share-class
# suffixes used in China.
_SHARE_CLASS_SUFFIX_RE = re.compile(r"\s?[ABCEH]$", re.IGNORECASE)


@dataclass
class FeatureMatrix:
    """Dense/sparse representation of product holding vectors."""

    report_date: Any  # date or str
    product_ids: np.ndarray
    product_codes: np.ndarray
    product_names: np.ndarray
    institution_codes: np.ndarray
    product_types: np.ndarray
    feature_names: np.ndarray  # asset codes or industry names
    feature_type: str  # "asset" or "industry"
    X: np.ndarray  # (n_products, n_features) weight matrix (possibly normalized)
    raw_weights: np.ndarray  # (n_products, n_features) original weights
    merge_map: dict[int, list[int]] = field(
        default_factory=dict
    )  # kept_id -> merged product_ids

    @property
    def n_products(self) -> int:
        return self.X.shape[0]

    @property
    def n_features(self) -> int:
        return self.X.shape[1]

    # Backward-compatible alias for asset-code matrices.
    @property
    def asset_codes(self) -> np.ndarray:
        return self.feature_names

    @property
    def n_assets(self) -> int:
        return self.X.shape[1]

    def to_dataframe(self) -> pd.DataFrame:
        """Return a DataFrame with products as rows and features as columns."""
        return pd.DataFrame(
            self.X,
            index=pd.MultiIndex.from_arrays(
                [self.product_ids, self.product_codes, self.product_names],
                names=["product_id", "product_code", "product_name"],
            ),
            columns=self.feature_names,
        )


def _base_name(name: str) -> str:
    """Return the product family name with trailing share-class suffix removed."""
    return _SHARE_CLASS_SUFFIX_RE.sub("", name.strip()).strip()


def _has_share_class_suffix(name: str) -> bool:
    """Return True if the product name ends with a known share-class suffix."""
    return bool(_SHARE_CLASS_SUFFIX_RE.search(name.strip()))


def deduplicate_ac_shares(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[int, list[int]]]:
    """Keep only one share class per product family.

    Primary rule: products from the same institution whose base name (with
    trailing A/B/C/E/H removed) are identical are candidates for merging.
    To avoid collapsing unrelated products that happen to share a base name
    (e.g. ``医药基金`` and ``医药基金A``), we only merge when at least two
    distinct products in the group carry an explicit share-class suffix.

    Returns:
        A tuple of (kept DataFrame, merge_map) where merge_map maps the kept
        ``product_id`` to the list of ``product_id``s that were merged into it
        (including the kept id itself).
    """
    df = df.copy()
    df["base_name"] = df["product_name"].apply(_base_name)
    df["has_suffix"] = df["product_name"].apply(_has_share_class_suffix)
    df["holding_count"] = df.groupby("product_id")["product_id"].transform("count")

    # One row per product within each (institution, base_name) candidate group.
    product_meta = (
        df.groupby(
            ["institution_code", "base_name", "product_id"], as_index=False
        )
        .agg(holding_count=("holding_count", "first"), has_suffix=("has_suffix", "any"))
    )

    selected_ids: list[int] = []
    merge_map: dict[int, list[int]] = {}
    for (institution, base_name), group in product_meta.groupby(
        ["institution_code", "base_name"]
    ):
        if len(group) == 1:
            pid = int(group["product_id"].iloc[0])
            selected_ids.append(pid)
            merge_map.setdefault(pid, [pid])
            continue

        # Merge only if the group has at least two explicit share-class suffixes.
        # This prevents ``X`` and ``XA`` (a real product and a synthetic name)
        # from being treated as share classes.
        if group["has_suffix"].sum() >= 2:
            selected_pid = int(
                group.sort_values("holding_count", ascending=False).iloc[0][
                    "product_id"
                ]
            )
            selected_ids.append(selected_pid)
            merge_map[selected_pid] = [
                int(pid) for pid in group["product_id"].tolist()
            ]
        else:
            selected_ids.extend(int(pid) for pid in group["product_id"].tolist())
            for pid in group["product_id"]:
                merge_map.setdefault(int(pid), [int(pid)])

    kept_df = (
        df[df["product_id"].isin(selected_ids)]
        .drop(columns=["base_name", "has_suffix", "holding_count"])
        .reset_index(drop=True)
    )
    return kept_df, merge_map


def build_weight_matrix(
    data: HoldingData,
    deduplicate: bool = True,
    normalize: bool = True,
) -> FeatureMatrix:
    """Build a product × asset weight matrix from holding data.

    Args:
        data: HoldingData loaded from the database.
        deduplicate: Whether to merge A/C share classes.
        normalize: Whether to L2-normalize each product vector.

    Returns:
        FeatureMatrix containing the dense weight matrix and metadata.
    """
    df = data.to_dataframe()

    merge_map: dict[int, list[int]] = {}
    if deduplicate:
        df, merge_map = deduplicate_ac_shares(df)

    # Aggregate weights by (product, asset) in case of duplicates.
    df = (
        df.groupby(
            ["product_id", "product_code", "product_name", "institution_code", "product_type", "asset_code", "asset_name"],
            as_index=False,
        )["weight"]
        .sum()
    )

    # Build pivot table.
    pivot = df.pivot_table(
        index=["product_id", "product_code", "product_name", "institution_code", "product_type"],
        columns="asset_code",
        values="weight",
        aggfunc="sum",
        fill_value=0.0,
    )

    raw_weights = pivot.to_numpy(dtype=np.float64)
    X = raw_weights.copy()
    if normalize:
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        X = X / norms

    # Re-extract metadata aligned with pivot rows.
    index_df = pivot.index.to_frame(index=False)
    feature_names = pivot.columns.to_numpy()

    return FeatureMatrix(
        report_date=data.report_date,
        product_ids=index_df["product_id"].to_numpy(),
        product_codes=index_df["product_code"].to_numpy(),
        product_names=index_df["product_name"].to_numpy(),
        institution_codes=index_df["institution_code"].to_numpy(),
        product_types=index_df["product_type"].to_numpy(),
        feature_names=feature_names,
        feature_type="asset",
        X=X,
        raw_weights=raw_weights,
        merge_map=merge_map,
    )


def compute_hhi(weights: np.ndarray) -> float:
    """Compute Herfindahl-Hirschman Index for a weight vector."""
    return float(np.sum(weights * weights))


def build_industry_matrix(
    data: HoldingData,
    mapping: IndustryMapping | None = None,
    deduplicate: bool = True,
    normalize: bool = True,
) -> FeatureMatrix:
    """Build a product × industry weight matrix from holding data.

    Args:
        data: HoldingData loaded from the database.
        mapping: Optional pre-built industry mapping. If None, fetch from Eastmoney.
        deduplicate: Whether to merge A/C share classes.
        normalize: Whether to L2-normalize each product vector.

    Returns:
        FeatureMatrix with industries as feature columns.
    """
    df = data.to_dataframe()

    merge_map: dict[int, list[int]] = {}
    if deduplicate:
        df, merge_map = deduplicate_ac_shares(df)

    # Aggregate weights by (product, asset) in case of duplicates.
    df = (
        df.groupby(
            ["product_id", "product_code", "product_name", "institution_code", "product_type", "asset_code", "market"],
            as_index=False,
        )["weight"]
        .sum()
    )

    industry_df = build_industry_weights(df, mapping=mapping)

    # Merge industry weights back with product metadata.
    meta = (
        df[["product_id", "product_code", "product_name", "institution_code", "product_type"]]
        .drop_duplicates()
    )
    industry_df = industry_df.merge(meta, on="product_id", how="left")

    pivot = industry_df.pivot_table(
        index=["product_id", "product_code", "product_name", "institution_code", "product_type"],
        columns="industry_name",
        values="weight",
        aggfunc="sum",
        fill_value=0.0,
    )

    raw_weights = pivot.to_numpy(dtype=np.float64)
    X = raw_weights.copy()
    if normalize:
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        X = X / norms

    index_df = pivot.index.to_frame(index=False)
    feature_names = pivot.columns.to_numpy()

    return FeatureMatrix(
        report_date=data.report_date,
        product_ids=index_df["product_id"].to_numpy(),
        product_codes=index_df["product_code"].to_numpy(),
        product_names=index_df["product_name"].to_numpy(),
        institution_codes=index_df["institution_code"].to_numpy(),
        product_types=index_df["product_type"].to_numpy(),
        feature_names=feature_names,
        feature_type="industry",
        X=X,
        raw_weights=raw_weights,
        merge_map=merge_map,
    )
