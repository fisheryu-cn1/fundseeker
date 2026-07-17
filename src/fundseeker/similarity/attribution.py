"""Brinson attribution for clustered portfolio holdings."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text

from fundseeker.models.database import get_engine
from fundseeker.similarity.industry import IndustryMapping, load_industry_mapping_from_db


@dataclass
class AttributionResult:
    """Brinson attribution result for a single product."""

    product_id: int
    cluster_id: int
    total_return: float
    benchmark_return: float
    excess_return: float
    allocation_effect: float
    selection_effect: float
    interaction_effect: float
    rank_in_cluster: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _normalize(weights: pd.Series) -> pd.Series:
    """Normalize weights so they sum to 1, returning zeros if total is 0."""
    total = weights.sum()
    if total == 0:
        return weights
    return weights / total


def _symbol_code(code: str, market: str) -> str:
    return f"{market.upper()}{code}"


def _prepare_holdings(
    df: pd.DataFrame,
    mapping: IndustryMapping,
    returns: dict[str, float],
) -> pd.DataFrame:
    """Add symbol_code / industry_name / stock_return and drop missing quotes."""
    df = df.copy()
    df["symbol_code"] = df.apply(
        lambda r: _symbol_code(r["asset_code"], r["market"]), axis=1
    )
    df["industry_name"] = df.apply(
        lambda r: mapping.get(r["asset_code"], r["market"]) or "未知行业",
        axis=1,
    )
    df = df[df["symbol_code"].isin(returns)].copy()
    if df.empty:
        return df
    df["weight"] = df["weight"].astype(float)
    df["stock_return"] = df["symbol_code"].map(returns)
    return df


def _portfolio_industry_profile(holdings: pd.DataFrame) -> pd.DataFrame:
    """Compute per-product industry weights and returns."""
    weights = (
        holdings.groupby(["product_id", "industry_name"])["weight"]
        .sum()
        .groupby(level=0)
        .transform(_normalize)
        .reset_index(name="industry_weight")
    )
    returns = (
        holdings.groupby(["product_id", "industry_name"])
        .apply(
            lambda g: float(
                (g["weight"] * g["stock_return"]).sum() / g["weight"].sum()
                if g["weight"].sum() > 0
                else 0.0
            ),
            include_groups=False,
        )
        .reset_index(name="industry_return")
    )
    return weights.merge(returns, on=["product_id", "industry_name"], how="left")


def _benchmark_industry_profile(bench_df: pd.DataFrame) -> pd.DataFrame:
    """Compute aggregate benchmark industry weights and returns."""
    weights = (
        bench_df.groupby("industry_name")["weight"]
        .sum()
        .pipe(_normalize)
        .reset_index(name="benchmark_weight")
    )
    returns = (
        bench_df.groupby("industry_name")
        .apply(
            lambda g: float(
                (g["weight"] * g["stock_return"]).sum() / g["weight"].sum()
                if g["weight"].sum() > 0
                else 0.0
            ),
            include_groups=False,
        )
        .reset_index(name="benchmark_return")
    )
    return weights.merge(returns, on="industry_name", how="left")


def _load_cluster_holdings(
    report_date: date,
    product_ids: tuple[int, ...],
) -> pd.DataFrame:
    """Load holdings for a set of products on a report date."""
    engine = get_engine()
    placeholders = ",".join(f":pid{i}" for i in range(len(product_ids)))
    params: dict[str, Any] = {"report_date": report_date}
    params.update({f"pid{i}": v for i, v in enumerate(product_ids)})

    sql = f"""
    SELECT product_id, asset_code, market, asset_name, weight
    FROM product_holding
    WHERE report_date = :report_date
      AND asset_type = 'stock'
      AND product_id IN ({placeholders})
      AND weight IS NOT NULL
    """
    with engine.connect() as conn:
        df = pd.read_sql(text(sql), conn, params=params)
    return df


def _load_quote_returns(
    symbol_codes: set[str],
    start_date: date,
    end_date: date,
) -> dict[str, float]:
    """Load per-symbol simple returns over [start_date, end_date].

    Uses the closest available quote on or before each endpoint within a
    5-calendar-day window.
    """
    engine = get_engine()
    placeholders = ",".join(f":sym{i}" for i in range(len(symbol_codes)))
    symbols = list(symbol_codes)
    params: dict[str, Any] = {
        "start_min": date.fromordinal(max(0, start_date.toordinal() - 5)),
        "start_max": start_date,
        "end_min": date.fromordinal(max(0, end_date.toordinal() - 5)),
        "end_max": end_date,
    }
    params.update({f"sym{i}": v for i, v in enumerate(symbols)})

    sql = f"""
    WITH start_quotes AS (
        SELECT symbol_code, close_price,
               ROW_NUMBER() OVER (
                   PARTITION BY symbol_code ORDER BY quote_date DESC
               ) AS rn
        FROM market_quote
        WHERE symbol_code IN ({placeholders})
          AND quote_date BETWEEN :start_min AND :start_max
    ),
    end_quotes AS (
        SELECT symbol_code, close_price,
               ROW_NUMBER() OVER (
                   PARTITION BY symbol_code ORDER BY quote_date DESC
               ) AS rn
        FROM market_quote
        WHERE symbol_code IN ({placeholders})
          AND quote_date BETWEEN :end_min AND :end_max
    )
    SELECT s.symbol_code,
           s.close_price AS start_price,
           e.close_price AS end_price
    FROM start_quotes s
    INNER JOIN end_quotes e ON e.symbol_code = s.symbol_code
    WHERE s.rn = 1 AND e.rn = 1
    """
    with engine.connect() as conn:
        df = pd.read_sql(text(sql), conn, params=params)

    returns: dict[str, float] = {}
    for _, row in df.iterrows():
        start_price = row["start_price"]
        end_price = row["end_price"]
        if start_price and end_price and start_price > 0:
            returns[row["symbol_code"]] = float(end_price / start_price - 1.0)
    return returns


def attribute_products(
    report_date: date,
    start_date: date,
    end_date: date,
    members: list[dict[str, Any]],
    benchmark_holdings: pd.DataFrame | None = None,
) -> list[AttributionResult]:
    """Run Brinson attribution by industry for the given cluster members.

    Args:
        report_date: Holding report date used as the weight snapshot.
        start_date: Attribution window start.
        end_date: Attribution window end.
        members: Cluster members, each with ``product_id`` and ``cluster_id``.
        benchmark_holdings: Optional DataFrame with columns
            ``asset_code, market, weight`` representing an external benchmark
            (e.g. an index). If None, the cluster-average portfolio is used.

    Returns:
        List of ``AttributionResult`` objects ranked by excess return.
    """
    if not members:
        return []

    product_ids = tuple(int(m["product_id"]) for m in members)
    cluster_id = int(members[0]["cluster_id"])

    holdings = _load_cluster_holdings(report_date, product_ids)
    if holdings.empty:
        return []

    mapping = load_industry_mapping_from_db()

    # Collect all symbols we may need quotes for.
    needed_symbols = set(
        holdings.apply(lambda r: _symbol_code(r["asset_code"], r["market"]), axis=1)
    )
    if benchmark_holdings is not None and not benchmark_holdings.empty:
        needed_symbols.update(
            benchmark_holdings.apply(
                lambda r: _symbol_code(r["asset_code"], r["market"]), axis=1
            )
        )

    returns = _load_quote_returns(needed_symbols, start_date, end_date)

    holdings = _prepare_holdings(holdings, mapping, returns)
    if holdings.empty:
        return []

    portfolio = _portfolio_industry_profile(holdings)

    if benchmark_holdings is None or benchmark_holdings.empty:
        bench_df = holdings
    else:
        bench_df = _prepare_holdings(benchmark_holdings, mapping, returns)
        if bench_df.empty:
            return []

    benchmark = _benchmark_industry_profile(bench_df)

    # --- Brinson decomposition per product ---
    # Build a full Cartesian grid of (product_id, industry_name) against the
    # benchmark so that every product shares the same benchmark rows.
    product_ids_arr = portfolio["product_id"].unique()
    benchmark_grid = pd.DataFrame(
        [
            (pid, industry)
            for pid in product_ids_arr
            for industry in benchmark["industry_name"]
        ],
        columns=["product_id", "industry_name"],
    )
    merged = benchmark_grid.merge(benchmark, on="industry_name", how="left")
    merged = merged.merge(portfolio, on=["product_id", "industry_name"], how="left")
    merged = merged.fillna(0.0)

    # For industries where the product has no weight, set its industry return
    # equal to the benchmark return so that selection and interaction in that
    # sector are zero; only allocation captures the under/overweight decision.
    zero_weight_mask = merged["industry_weight"] == 0
    merged.loc[zero_weight_mask, "industry_return"] = merged.loc[
        zero_weight_mask, "benchmark_return"
    ]

    results: list[AttributionResult] = []
    for product_id, group in merged.groupby("product_id"):
        Wp = group["industry_weight"].to_numpy()
        Rp = group["industry_return"].to_numpy()
        Wb = group["benchmark_weight"].to_numpy()
        Rb = group["benchmark_return"].to_numpy()

        total_return = float(np.sum(Wp * Rp))
        benchmark_return = float(np.sum(Wb * Rb))
        allocation = float(np.sum((Wp - Wb) * Rb))
        selection = float(np.sum(Wb * (Rp - Rb)))
        interaction = float(np.sum((Wp - Wb) * (Rp - Rb)))
        excess = total_return - benchmark_return

        results.append(
            AttributionResult(
                product_id=int(product_id),
                cluster_id=cluster_id,
                total_return=total_return,
                benchmark_return=benchmark_return,
                excess_return=excess,
                allocation_effect=allocation,
                selection_effect=selection,
                interaction_effect=interaction,
            )
        )

    # Rank by excess return (higher is better).
    results.sort(key=lambda r: r.excess_return, reverse=True)
    for i, r in enumerate(results, start=1):
        r.rank_in_cluster = i

    return results
