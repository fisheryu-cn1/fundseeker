"""Data loading helpers for similarity analysis.

All functions are read-only and operate on the existing FundSeeker database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text

from fundseeker.models.database import get_engine


@dataclass
class HoldingData:
    """Container for raw holding data used by the similarity service."""

    report_date: date
    product_id: np.ndarray
    product_code: np.ndarray
    product_name: np.ndarray
    institution_code: np.ndarray
    product_type: np.ndarray
    asset_code: np.ndarray
    asset_name: np.ndarray
    market: np.ndarray
    weight: np.ndarray

    def to_dataframe(self) -> pd.DataFrame:
        """Return a DataFrame view of the data."""
        return pd.DataFrame(
            {
                "product_id": self.product_id,
                "product_code": self.product_code,
                "product_name": self.product_name,
                "institution_code": self.institution_code,
                "product_type": self.product_type,
                "asset_code": self.asset_code,
                "asset_name": self.asset_name,
                "market": self.market,
                "weight": self.weight,
            }
        )


def load_holdings(
    report_date: date | str,
    product_types: tuple[str, ...] | list[str] | None = None,
    asset_types: tuple[str, ...] | list[str] | None = None,
    min_holdings: int = 3,
) -> HoldingData:
    """Load the latest product snapshots with holdings for a report date.

    Args:
        report_date: Target holding report date.
        product_types: Filter by product_type codes (e.g. ["equity", "mixed"]).
        asset_types: Filter by asset_type codes (e.g. ["stock"]).
        min_holdings: Minimum number of holdings required for inclusion.

    Returns:
        A HoldingData object containing the filtered rows.
    """
    if isinstance(report_date, str):
        report_date = date.fromisoformat(report_date)

    product_types = product_types or ("equity", "mixed")
    asset_types = asset_types or ("stock",)

    product_type_placeholders = ",".join(f":pt{i}" for i in range(len(product_types)))
    asset_type_placeholders = ",".join(f":at{i}" for i in range(len(asset_types)))

    params: dict[str, Any] = {"report_date": report_date}
    params.update({f"pt{i}": v for i, v in enumerate(product_types)})
    params.update({f"at{i}": v for i, v in enumerate(asset_types)})

    sql = f"""
    WITH holding_products AS (
        SELECT DISTINCT product_id
        FROM product_holding
        WHERE report_date = :report_date
    ),
    latest_snapshot AS (
        SELECT
            p.id AS product_id,
            p.product_code,
            p.product_name,
            p.institution_code,
            p.product_type,
            ROW_NUMBER() OVER (
                PARTITION BY p.product_code ORDER BY p.collect_date DESC
            ) AS rn
        FROM product_info p
        INNER JOIN holding_products hp ON hp.product_id = p.id
        WHERE p.product_type IN ({product_type_placeholders})
    ),
    qualified AS (
        SELECT ls.product_id
        FROM latest_snapshot ls
        INNER JOIN product_holding h
            ON h.product_id = ls.product_id AND h.report_date = :report_date
        WHERE ls.rn = 1
          AND h.asset_type IN ({asset_type_placeholders})
          AND h.weight IS NOT NULL
        GROUP BY ls.product_id
        HAVING COUNT(DISTINCT h.asset_code) >= :min_holdings
    )
    SELECT
        ls.product_id,
        ls.product_code,
        ls.product_name,
        ls.institution_code,
        ls.product_type,
        h.asset_code,
        h.asset_name,
        h.market,
        h.weight
    FROM latest_snapshot ls
    INNER JOIN qualified q ON q.product_id = ls.product_id
    INNER JOIN product_holding h
        ON h.product_id = ls.product_id AND h.report_date = :report_date
    WHERE ls.rn = 1
      AND h.asset_type IN ({asset_type_placeholders})
      AND h.weight IS NOT NULL
    ORDER BY ls.product_id, h.sort_order, h.asset_code
    """

    engine = get_engine()
    params["min_holdings"] = min_holdings
    with engine.connect() as conn:
        df = pd.read_sql(text(sql), conn, params=params)

    if df.empty:
        raise ValueError(
            f"No holdings found for report_date={report_date}, "
            f"product_types={product_types}, asset_types={asset_types}"
        )

    return HoldingData(
        report_date=report_date,
        product_id=df["product_id"].to_numpy(),
        product_code=df["product_code"].to_numpy(),
        product_name=df["product_name"].to_numpy(),
        institution_code=df["institution_code"].to_numpy(),
        product_type=df["product_type"].to_numpy(),
        asset_code=df["asset_code"].to_numpy(),
        asset_name=df["asset_name"].to_numpy(),
        market=df["market"].to_numpy(),
        weight=df["weight"].to_numpy(dtype=np.float64),
    )
