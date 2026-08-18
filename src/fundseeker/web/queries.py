"""DB query helpers for the read-only Web UI.

All functions are read-only and reuse the existing SQLAlchemy models and engine
helpers from ``fundseeker.models``. They are intentionally kept here (rather
than inlined in route handlers) so they can be unit-tested or reused by a
future export script.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import desc, distinct, func, select
from sqlalchemy.orm import aliased

from fundseeker.models.database import get_session_maker
from fundseeker.similarity.labels import derive_cluster_label
from fundseeker.models.tables import (
    CollectionLog,
    HoldingReport,
    HoldingSecurityInfo,
    MarketQuote,
    ProductAssetAllocation,
    ProductHolding,
    ProductHoldingSummary,
    ProductInfo,
    ProductManagerStyle,
    ProductNav,
    SimilarityCluster,
    SimilarityClusterMember,
    SimilarityClusterRun,
)


# ---------------------------------------------------------------------------
# Constants used in the UI
# ---------------------------------------------------------------------------

PRODUCT_TYPES: list[tuple[str, str]] = [
    ("equity", "股票型 / 权益类"),
    ("mixed", "混合型"),
    ("fixed_income", "债券型 / 固定收益"),
    ("index", "指数型"),
    ("money_market", "货币型 / 现金管理"),
    ("qdii", "QDII"),
    ("fof", "FOF / 养老"),
    ("commodity", "商品型"),
    ("other", "其他"),
]

RISK_LEVELS: list[str] = ["L1", "L2", "L3", "L4", "L5"]

# Asset type filter values for the holdings browse page.
HOLDING_ASSET_TYPES: list[tuple[str, str]] = [
    ("stock", "股票"),
    ("bond", "债券"),
    ("fund", "基金"),
    ("cash", "现金 / 存款"),
    ("deposit", "银行存款"),
    ("derivative", "衍生品"),
    ("other", "其他"),
]

HOLDING_MARKETS: list[tuple[str, str]] = [
    ("SH", "上海"),
    ("SZ", "深圳"),
    ("BJ", "北京"),
    ("HK", "港股"),
    ("US", "美股"),
    ("CN_INTERBANK", "银行间"),
    ("OTC", "场外"),
    ("UNKNOWN", "未识别"),
]

MARKET_REGIONS: list[tuple[str, str]] = [
    ("domestic", "A股"),
    ("us", "美股"),
    ("hk", "港股"),
    ("commodity", "大宗商品"),
]

MARKET_ASSET_CLASSES: list[tuple[str, str]] = [
    ("index", "指数"),
    ("commodity", "商品"),
]

# Default asset_class filter for the market dashboard. Excludes ``stock``
# rows, which are pulled in by stock-quote backfill and are not meant to
# appear in the macro market view.
_DEFAULT_MARKET_ASSET_CLASSES: tuple[str, ...] = tuple(
    code for code, _ in MARKET_ASSET_CLASSES
)


# ---------------------------------------------------------------------------
# Dataclasses — ORM-free results that are easy to serialise / template
# ---------------------------------------------------------------------------


@dataclass
class ProductRow:
    """One row in the search results table."""

    id: int
    institution_code: str
    product_code: str
    product_name: str
    product_type: str
    risk_level_standard: str
    status: str
    latest_nav_date: datetime | None
    latest_unit_nav: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "institution_code": self.institution_code,
            "product_code": self.product_code,
            "product_name": self.product_name,
            "product_type": self.product_type,
            "risk_level_standard": self.risk_level_standard,
            "status": self.status,
            "latest_nav_date": (
                self.latest_nav_date.isoformat() if self.latest_nav_date else None
            ),
            "latest_unit_nav": (
                float(self.latest_unit_nav) if self.latest_unit_nav is not None else None
            ),
        }


@dataclass
class HoldingReportRow:
    """One row in the per-product holding-report timeline."""

    id: int
    report_date: date
    report_type: str
    report_period: str | None
    data_source: str
    holding_count: int | None
    top10_weight: float | None


@dataclass
class HoldingRow:
    """One row in the holding detail table."""

    id: int
    report_id: int
    report_date: date
    asset_code: str | None
    asset_name: str
    asset_type: str
    sub_type: str | None
    market: str | None
    industry_name: str | None
    weight: float | None
    market_value: float | None
    share_quantity: float | None
    is_top10: bool | None
    sort_order: int | None


@dataclass
class AssetAllocationRow:
    """One row of the high-level asset allocation table."""

    asset_class: str
    weight: float | None
    market_value: float | None


@dataclass
class HoldingBrowseRow:
    """One row of the cross-product holding search page."""

    holding_id: int
    product_id: int
    product_code: str
    product_name: str
    institution_code: str
    report_date: date
    report_period: str | None
    asset_code: str | None
    asset_name: str
    asset_type: str
    sub_type: str | None
    market: str | None
    industry_name: str | None
    weight: float | None
    market_value: float | None
    share_quantity: float | None
    is_top10: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "holding_id": self.holding_id,
            "product_id": self.product_id,
            "product_code": self.product_code,
            "product_name": self.product_name,
            "institution_code": self.institution_code,
            "report_date": self.report_date.isoformat(),
            "report_period": self.report_period,
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "asset_type": self.asset_type,
            "sub_type": self.sub_type,
            "market": self.market,
            "industry_name": self.industry_name,
            "weight": float(self.weight) if self.weight is not None else None,
            "market_value": (
                float(self.market_value) if self.market_value is not None else None
            ),
            "share_quantity": (
                float(self.share_quantity) if self.share_quantity is not None else None
            ),
            "is_top10": self.is_top10,
        }


@dataclass
class MarketQuoteRow:
    """One row in the market quote table / KPI card."""

    quote_date: date
    symbol_code: str
    symbol_name: str
    market_region: str
    asset_class: str
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    prev_close: float | None
    change_amount: float | None
    change_pct: float | None
    volume: int | None
    volume_unit: str | None
    amount: float | None
    currency: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "quote_date": self.quote_date.isoformat(),
            "symbol_code": self.symbol_code,
            "symbol_name": self.symbol_name,
            "market_region": self.market_region,
            "asset_class": self.asset_class,
            "open_price": float(self.open_price) if self.open_price is not None else None,
            "high_price": float(self.high_price) if self.high_price is not None else None,
            "low_price": float(self.low_price) if self.low_price is not None else None,
            "close_price": float(self.close_price) if self.close_price is not None else None,
            "prev_close": float(self.prev_close) if self.prev_close is not None else None,
            "change_amount": float(self.change_amount) if self.change_amount is not None else None,
            "change_pct": float(self.change_pct) if self.change_pct is not None else None,
            "volume": self.volume,
            "volume_unit": self.volume_unit,
            "amount": float(self.amount) if self.amount is not None else None,
            "currency": self.currency,
        }


# ---------------------------------------------------------------------------
# Similarity-analysis datatypes
# ---------------------------------------------------------------------------


@dataclass
class SimilarityRunRow:
    """One row in the persisted similarity run list."""

    cluster_run_id: int
    report_date: date
    algorithm: str
    k: int
    product_type_filter: str | None
    n_products: int | None
    n_features: int | None
    silhouette: float | None
    inertia: float | None
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_run_id": self.cluster_run_id,
            "report_date": self.report_date.isoformat(),
            "algorithm": self.algorithm,
            "k": self.k,
            "product_type_filter": self.product_type_filter,
            "n_products": self.n_products,
            "n_features": self.n_features,
            "silhouette": float(self.silhouette) if self.silhouette is not None else None,
            "inertia": float(self.inertia) if self.inertia is not None else None,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class SimilarityClusterRow:
    """One row in a run's cluster summary."""

    cluster_id: int
    size: int
    cluster_label: str | None
    top_holdings: list[dict[str, Any]]
    top_industries: list[dict[str, Any]]
    avg_hhi: float | None
    avg_overlap: float | None
    avg_overlap_raw: float | None
    ac_share_dominance_ratio: float | None
    institution_distribution: dict[str, int]
    representative_products: list[int]
    representative_codes: list[str]
    representative_names: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "size": self.size,
            "cluster_label": self.cluster_label,
            "top_holdings": self.top_holdings,
            "top_industries": self.top_industries,
            "avg_hhi": float(self.avg_hhi) if self.avg_hhi is not None else None,
            "avg_overlap": float(self.avg_overlap) if self.avg_overlap is not None else None,
            "avg_overlap_raw": float(self.avg_overlap_raw) if self.avg_overlap_raw is not None else None,
            "ac_share_dominance_ratio": (
                float(self.ac_share_dominance_ratio)
                if self.ac_share_dominance_ratio is not None
                else None
            ),
            "institution_distribution": self.institution_distribution,
            "representative_products": self.representative_products,
            "representative_codes": self.representative_codes,
            "representative_names": self.representative_names,
        }


@dataclass
class SimilarityMemberRow:
    """One member in a cluster."""

    product_id: int
    institution_code: str
    product_code: str
    product_name: str
    product_type: str
    cluster_id: int
    distance_to_center: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "institution_code": self.institution_code,
            "product_code": self.product_code,
            "product_name": self.product_name,
            "product_type": self.product_type,
            "cluster_id": self.cluster_id,
            "distance_to_center": (
                float(self.distance_to_center)
                if self.distance_to_center is not None
                else None
            ),
        }


@dataclass
class SimilarityRunDetail:
    """Full detail of a single similarity run (run + clusters + members)."""

    run: SimilarityRunRow
    clusters: list[SimilarityClusterRow]
    members: list[SimilarityMemberRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run.to_dict(),
            "clusters": [c.to_dict() for c in self.clusters],
            "members": [m.to_dict() for m in self.members],
        }


# Asset-type → market index bundles used by cluster_market_overlay().
# Selection is driven by the cluster's actual asset composition
# (HK stocks → HSI; US stocks → NDX/SPX/DJIA; A-shares → CSI/Shenzhen indices).
MARKET_INDEX_BUNDLES: dict[str, list[str]] = {
    "domestic": ["SH000300", "SH000001", "SZ399006"],
    "hk": ["HSI"],
    "us": ["NDX", "SPX", "DJIA"],
    "commodity": ["GOLD", "BRENT_OIL"],
    "baseline": ["SH000300"],  # always included as a domestic reference
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session():
    """Return a fresh SQLAlchemy session."""
    engine = get_session_maker().kw["bind"]
    Session = get_session_maker(engine)
    return Session()


def _humanize_asset_class(value: str | None) -> str:
    """Map an asset_class code to a human-readable label."""
    mapping = dict(HOLDING_ASSET_TYPES)
    if not value:
        return "—"
    return mapping.get(value, value)


def humanize_asset_class(value: str | None) -> str:
    """Public wrapper used by templates that need a quick label."""
    return _humanize_asset_class(value)


def humanize_market(value: str | None) -> str:
    """Map a market code to a human-readable label."""
    if not value:
        return "—"
    mapping = dict(HOLDING_MARKETS)
    return mapping.get(value, value)


def distinct_institutions() -> list[str]:
    """Institution codes that actually have rows in product_info."""
    with _session() as session:
        rows = session.execute(
            select(distinct(ProductInfo.institution_code))
            .order_by(ProductInfo.institution_code)
        ).all()
    return [r[0] for r in rows]


def distinct_statuses() -> list[str]:
    """Distinct status values present in product_info (drives the status filter)."""
    with _session() as session:
        rows = session.execute(
            select(distinct(ProductInfo.status))
            .order_by(ProductInfo.status)
        ).all()
    return [r[0] for r in rows]


def distinct_holding_asset_types() -> list[str]:
    """Asset types actually present in product_holding."""
    with _session() as session:
        rows = session.execute(
            select(distinct(ProductHolding.asset_type))
            .order_by(ProductHolding.asset_type)
        ).all()
    return [r[0] for r in rows]


def humanize_market_region(value: str | None) -> str:
    """Map a market_region code to a human-readable label."""
    if not value:
        return "—"
    return dict(MARKET_REGIONS).get(value, value)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def list_products(
    *,
    institution: str | None = None,
    product_type: str | None = None,
    risk: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[ProductRow], int]:
    """Return ``(items, total)`` for the search page.

    Filters are AND-combined. ``keyword`` matches either product_code or
    product_name (ILIKE on PostgreSQL).
    """
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 200:
        page_size = 25

    filters = []
    if institution:
        filters.append(ProductInfo.institution_code == institution)
    if product_type:
        filters.append(ProductInfo.product_type == product_type)
    if risk:
        filters.append(ProductInfo.risk_level_standard == risk)
    if status:
        filters.append(ProductInfo.status == status)
    if keyword:
        kw = f"%{keyword.strip()}%"
        filters.append(
            (ProductInfo.product_code.ilike(kw))
            | (ProductInfo.product_name.ilike(kw))
        )

    with _session() as session:
        total: int = session.execute(
            select(func.count(ProductInfo.id)).where(*filters)
        ).scalar_one()

        # Latest nav per product via correlated subquery. With only ~6k rows
        # this is fast; if it ever isn't, switch to a window function.
        latest = (
            select(
                ProductNav.product_id,
                func.max(ProductNav.nav_date).label("max_date"),
            )
            .group_by(ProductNav.product_id)
            .subquery()
        )
        nav_alias = aliased(ProductNav)
        latest_nav_join = (
            select(
                nav_alias.product_id,
                nav_alias.nav_date,
                nav_alias.unit_nav,
            )
            .join(
                latest,
                (nav_alias.product_id == latest.c.product_id)
                & (nav_alias.nav_date == latest.c.max_date),
            )
            .subquery()
        )

        rows_stmt = (
            select(
                ProductInfo.id,
                ProductInfo.institution_code,
                ProductInfo.product_code,
                ProductInfo.product_name,
                ProductInfo.product_type,
                ProductInfo.risk_level_standard,
                ProductInfo.status,
                latest_nav_join.c.nav_date,
                latest_nav_join.c.unit_nav,
            )
            .select_from(ProductInfo)
            .outerjoin(
                latest_nav_join,
                latest_nav_join.c.product_id == ProductInfo.id,
            )
            .where(*filters)
            .order_by(
                ProductInfo.institution_code,
                ProductInfo.product_code,
            )
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        rows = session.execute(rows_stmt).all()

    items = [
        ProductRow(
            id=r[0],
            institution_code=r[1],
            product_code=r[2],
            product_name=r[3],
            product_type=r[4],
            risk_level_standard=r[5],
            status=r[6],
            latest_nav_date=r[7],
            latest_unit_nav=r[8],
        )
        for r in rows
    ]
    return items, total


# ---------------------------------------------------------------------------
# Product detail
# ---------------------------------------------------------------------------


def get_product(product_id: int) -> ProductInfo | None:
    with _session() as session:
        return session.get(ProductInfo, product_id)


def list_nav(product_id: int, limit: int = 50) -> list[ProductNav]:
    with _session() as session:
        stmt = (
            select(ProductNav)
            .where(ProductNav.product_id == product_id)
            .order_by(ProductNav.nav_date.desc())
            .limit(limit)
        )
        return list(session.execute(stmt).scalars())


def nav_count(product_id: int) -> int:
    with _session() as session:
        return session.execute(
            select(func.count(ProductNav.id)).where(
                ProductNav.product_id == product_id
            )
        ).scalar_one()


def list_nav_by_product_code(
    institution_code: str, product_code: str, limit: int = 50
) -> list[ProductNav]:
    """Return NAV history for the logical product across all snapshots.

    ``product_info`` is a daily snapshot table, so the same logical product
    has multiple rows (and therefore multiple ``product_id`` values). This
    helper aggregates ``product_nav`` across all snapshots of the same
    ``(institution_code, product_code)`` pair and returns the latest
    ``limit`` distinct records ordered by nav_date descending.
    """
    with _session() as session:
        product_ids = select(ProductInfo.id).where(
            ProductInfo.institution_code == institution_code,
            ProductInfo.product_code == product_code,
        ).scalar_subquery()
        # Use DISTINCT ON to keep one NAV per date in case snapshots overlap.
        stmt = (
            select(ProductNav)
            .where(ProductNav.product_id.in_(product_ids))
            .distinct(ProductNav.nav_date)
            .order_by(ProductNav.nav_date.desc(), ProductNav.id.desc())
            .limit(limit)
        )
        rows = list(session.execute(stmt).scalars())
    rows.reverse()
    return rows


def nav_count_by_product_code(institution_code: str, product_code: str) -> int:
    """Count distinct NAV dates for the logical product across snapshots."""
    with _session() as session:
        product_ids = select(ProductInfo.id).where(
            ProductInfo.institution_code == institution_code,
            ProductInfo.product_code == product_code,
        ).scalar_subquery()
        return session.execute(
            select(func.count(distinct(ProductNav.nav_date))).where(
                ProductNav.product_id.in_(product_ids)
            )
        ).scalar_one()


def list_returns(product_id: int) -> list[Any]:
    # Imported lazily to avoid a hard dep on the return table staying empty.
    from fundseeker.models.tables import ProductReturn

    with _session() as session:
        stmt = (
            select(ProductReturn)
            .where(ProductReturn.product_id == product_id)
            .order_by(ProductReturn.return_period, ProductReturn.calc_date.desc())
        )
        return list(session.execute(stmt).scalars())


def list_fees(product_id: int) -> list[Any]:
    from fundseeker.models.tables import ProductFee

    with _session() as session:
        stmt = (
            select(ProductFee)
            .where(ProductFee.product_id == product_id)
            .order_by(ProductFee.fee_type)
        )
        return list(session.execute(stmt).scalars())


def recent_logs_for_institution(
    institution_code: str, limit: int = 5
) -> list[CollectionLog]:
    with _session() as session:
        stmt = (
            select(CollectionLog)
            .where(CollectionLog.institution_code == institution_code)
            .order_by(CollectionLog.start_time.desc())
            .limit(limit)
        )
        return list(session.execute(stmt).scalars())


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------


def list_holding_reports(product_id: int) -> list[HoldingReportRow]:
    """All holding reports for a product, latest first, with summary metrics."""
    with _session() as session:
        stmt = (
            select(
                HoldingReport.id,
                HoldingReport.report_date,
                HoldingReport.report_type,
                HoldingReport.report_period,
                HoldingReport.data_source,
                ProductHoldingSummary.holding_count,
                ProductHoldingSummary.top10_weight,
            )
            .outerjoin(
                ProductHoldingSummary,
                ProductHoldingSummary.report_id == HoldingReport.id,
            )
            .where(HoldingReport.product_id == product_id)
            .order_by(HoldingReport.report_date.desc())
        )
        rows = session.execute(stmt).all()
    return [
        HoldingReportRow(
            id=r[0],
            report_date=r[1],
            report_type=r[2],
            report_period=r[3],
            data_source=r[4],
            holding_count=r[5],
            top10_weight=r[6],
        )
        for r in rows
    ]


def latest_holding_report(product_id: int) -> HoldingReport | None:
    """Return the most recent HoldingReport for a product (by report_date)."""
    with _session() as session:
        return session.execute(
            select(HoldingReport)
            .where(HoldingReport.product_id == product_id)
            .order_by(HoldingReport.report_date.desc())
            .limit(1)
        ).scalar_one_or_none()


def list_holding_reports_by_product_code(
    institution_code: str, product_code: str
) -> list[HoldingReportRow]:
    """All holding reports for the logical product across snapshots.

    Deduplicates by ``report_date``; if multiple snapshots collected the same
    report date, the one from the most recent ``product_info`` snapshot is kept.
    """
    with _session() as session:
        # Join with product_info so we can rank snapshots by collect_date.
        ranked = (
            select(
                HoldingReport.id,
                HoldingReport.report_date,
                HoldingReport.report_type,
                HoldingReport.report_period,
                HoldingReport.data_source,
                ProductHoldingSummary.holding_count,
                ProductHoldingSummary.top10_weight,
                ProductInfo.collect_date,
                func.row_number()
                .over(
                    partition_by=HoldingReport.report_date,
                    order_by=ProductInfo.collect_date.desc(),
                )
                .label("rn"),
            )
            .join(
                ProductInfo,
                ProductInfo.id == HoldingReport.product_id,
            )
            .outerjoin(
                ProductHoldingSummary,
                ProductHoldingSummary.report_id == HoldingReport.id,
            )
            .where(
                ProductInfo.institution_code == institution_code,
                ProductInfo.product_code == product_code,
            )
            .subquery()
        )
        stmt = (
            select(
                ranked.c.id,
                ranked.c.report_date,
                ranked.c.report_type,
                ranked.c.report_period,
                ranked.c.data_source,
                ranked.c.holding_count,
                ranked.c.top10_weight,
            )
            .where(ranked.c.rn == 1)
            .order_by(ranked.c.report_date.desc())
        )
        rows = session.execute(stmt).all()
    return [
        HoldingReportRow(
            id=r[0],
            report_date=r[1],
            report_type=r[2],
            report_period=r[3],
            data_source=r[4],
            holding_count=r[5],
            top10_weight=r[6],
        )
        for r in rows
    ]


def latest_holding_report_by_product_code(
    institution_code: str, product_code: str
) -> HoldingReport | None:
    """Return the most recent HoldingReport for the logical product.

    If the same report_date exists across multiple snapshots, prefer the one
    from the most recent ``product_info`` snapshot.
    """
    with _session() as session:
        return session.execute(
            select(HoldingReport)
            .join(ProductInfo, ProductInfo.id == HoldingReport.product_id)
            .where(
                ProductInfo.institution_code == institution_code,
                ProductInfo.product_code == product_code,
            )
            .order_by(HoldingReport.report_date.desc(), ProductInfo.collect_date.desc())
            .limit(1)
        ).scalar_one_or_none()


def list_holdings(
    report_id: int,
    *,
    asset_type: str | None = None,
    only_top10: bool = False,
) -> list[HoldingRow]:
    """Return holding rows for a report, sorted by weight desc."""
    with _session() as session:
        stmt = select(ProductHolding).where(ProductHolding.report_id == report_id)
        if asset_type:
            stmt = stmt.where(ProductHolding.asset_type == asset_type)
        if only_top10:
            stmt = stmt.where(ProductHolding.is_top10.is_(True))
        stmt = stmt.order_by(
            ProductHolding.sort_order.asc().nulls_last(),
            ProductHolding.weight.desc().nulls_last(),
            ProductHolding.asset_name.asc(),
        )
        rows = list(session.execute(stmt).scalars())
    return [
        HoldingRow(
            id=r.id,
            report_id=r.report_id,
            report_date=r.report_date,
            asset_code=r.asset_code,
            asset_name=r.asset_name,
            asset_type=r.asset_type,
            sub_type=r.sub_type,
            market=r.market,
            industry_name=r.industry_name,
            weight=r.weight,
            market_value=r.market_value,
            share_quantity=r.share_quantity,
            is_top10=r.is_top10,
            sort_order=r.sort_order,
        )
        for r in rows
    ]


def list_asset_allocation(report_id: int) -> list[AssetAllocationRow]:
    """Return asset allocation rows for a report."""
    with _session() as session:
        stmt = (
            select(ProductAssetAllocation)
            .where(ProductAssetAllocation.report_id == report_id)
            .order_by(ProductAssetAllocation.weight.desc().nulls_last())
        )
        rows = list(session.execute(stmt).scalars())
    return [
        AssetAllocationRow(
            asset_class=r.asset_class,
            weight=r.weight,
            market_value=r.market_value,
        )
        for r in rows
    ]


def get_holding_summary(report_id: int) -> ProductHoldingSummary | None:
    with _session() as session:
        return session.execute(
            select(ProductHoldingSummary).where(
                ProductHoldingSummary.report_id == report_id
            )
        ).scalar_one_or_none()


def list_style_tags(
    product_id: int, report_date: date | None = None
) -> list[ProductManagerStyle]:
    with _session() as session:
        stmt = select(ProductManagerStyle).where(
            ProductManagerStyle.product_id == product_id
        )
        if report_date is not None:
            stmt = stmt.where(ProductManagerStyle.report_date == report_date)
        stmt = stmt.order_by(
            ProductManagerStyle.report_date.desc(),
            ProductManagerStyle.dimension,
            ProductManagerStyle.tag,
        )
        return list(session.execute(stmt).scalars())


def get_security_info(
    asset_code: str, market: str | None = None
) -> HoldingSecurityInfo | None:
    """Look up a security reference row by code (and optional market)."""
    if not asset_code:
        return None
    with _session() as session:
        stmt = select(HoldingSecurityInfo).where(
            HoldingSecurityInfo.asset_code == asset_code
        )
        if market:
            stmt = stmt.where(HoldingSecurityInfo.market == market)
        return session.execute(stmt.limit(1)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Holdings browse — cross-product search
# ---------------------------------------------------------------------------


def search_holdings(
    *,
    asset_type: str | None = None,
    market: str | None = None,
    institution: str | None = None,
    asset_keyword: str | None = None,
    min_weight: float | None = None,
    only_top10: bool = False,
    report_date: date | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[HoldingBrowseRow], int]:
    """Return ``(rows, total)`` for the cross-product holdings browse page."""
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 200:
        page_size = 25

    filters = []
    if asset_type:
        filters.append(ProductHolding.asset_type == asset_type)
    if market:
        filters.append(ProductHolding.market == market)
    if institution:
        filters.append(ProductInfo.institution_code == institution)
    if asset_keyword:
        kw = f"%{asset_keyword.strip()}%"
        filters.append(
            (ProductHolding.asset_code.ilike(kw))
            | (ProductHolding.asset_name.ilike(kw))
            | (ProductHolding.industry_name.ilike(kw))
        )
    if min_weight is not None:
        filters.append(ProductHolding.weight >= min_weight)
    if only_top10:
        filters.append(ProductHolding.is_top10.is_(True))
    if report_date is not None:
        filters.append(ProductHolding.report_date == report_date)

    with _session() as session:
        total: int = session.execute(
            select(func.count(ProductHolding.id))
            .select_from(ProductHolding)
            .join(ProductInfo, ProductInfo.id == ProductHolding.product_id)
            .where(*filters)
        ).scalar_one()

        stmt = (
            select(
                ProductHolding.id,
                ProductInfo.id,
                ProductInfo.product_code,
                ProductInfo.product_name,
                ProductInfo.institution_code,
                ProductHolding.report_date,
                HoldingReport.report_period,
                ProductHolding.asset_code,
                ProductHolding.asset_name,
                ProductHolding.asset_type,
                ProductHolding.sub_type,
                ProductHolding.market,
                ProductHolding.industry_name,
                ProductHolding.weight,
                ProductHolding.market_value,
                ProductHolding.share_quantity,
                ProductHolding.is_top10,
            )
            .join(ProductInfo, ProductInfo.id == ProductHolding.product_id)
            .outerjoin(
                HoldingReport, HoldingReport.id == ProductHolding.report_id
            )
            .where(*filters)
            .order_by(
                ProductHolding.weight.desc().nulls_last(),
                ProductHolding.report_date.desc(),
                ProductHolding.sort_order.asc().nulls_last(),
            )
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        rows = session.execute(stmt).all()

    return [
        HoldingBrowseRow(
            holding_id=r[0],
            product_id=r[1],
            product_code=r[2],
            product_name=r[3],
            institution_code=r[4],
            report_date=r[5],
            report_period=r[6],
            asset_code=r[7],
            asset_name=r[8],
            asset_type=r[9],
            sub_type=r[10],
            market=r[11],
            industry_name=r[12],
            weight=r[13],
            market_value=r[14],
            share_quantity=r[15],
            is_top10=r[16],
        )
        for r in rows
    ], total


def distinct_holding_report_dates(limit: int = 12) -> list[date]:
    """Most recent distinct report dates present in product_holding."""
    with _session() as session:
        rows = session.execute(
            select(distinct(ProductHolding.report_date))
            .order_by(ProductHolding.report_date.desc())
            .limit(limit)
        ).all()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Market quotes
# ---------------------------------------------------------------------------


def _row_to_market_quote(row) -> MarketQuoteRow:
    return MarketQuoteRow(
        quote_date=row[0],
        symbol_code=row[1],
        symbol_name=row[2],
        market_region=row[3],
        asset_class=row[4],
        open_price=row[5],
        high_price=row[6],
        low_price=row[7],
        close_price=row[8],
        prev_close=row[9],
        change_amount=row[10],
        change_pct=row[11],
        volume=row[12],
        volume_unit=row[13],
        amount=row[14],
        currency=row[15],
    )


_MARKET_QUOTE_COLS = [
    MarketQuote.quote_date,
    MarketQuote.symbol_code,
    MarketQuote.symbol_name,
    MarketQuote.market_region,
    MarketQuote.asset_class,
    MarketQuote.open_price,
    MarketQuote.high_price,
    MarketQuote.low_price,
    MarketQuote.close_price,
    MarketQuote.prev_close,
    MarketQuote.change_amount,
    MarketQuote.change_pct,
    MarketQuote.volume,
    MarketQuote.volume_unit,
    MarketQuote.amount,
    MarketQuote.currency,
]


def list_market_quotes(
    *,
    quote_date: date | None = None,
    region: str | None = None,
    asset_classes: tuple[str, ...] | list[str] | None = _DEFAULT_MARKET_ASSET_CLASSES,
) -> list[MarketQuoteRow]:
    """Return quotes for a given date, or each symbol's latest when date is None.

    This avoids the problem where the absolute latest date only has partial
    data (e.g. commodities update before indices on the same calendar day).

    Args:
        quote_date: Specific calendar date; when ``None``, each symbol's
            most recent record is returned.
        region: Filter by ``market_region`` (domestic/us/hk/commodity).
        asset_classes: Filter by ``asset_class`` (index/commodity). Defaults
            to the macro-market view which excludes ``stock`` rows. Pass an
            empty tuple/list to disable the filter.
    """
    asset_filter = (
        tuple(asset_classes) if asset_classes is not None else ()
    )

    with _session() as session:
        if quote_date is not None:
            filters = [MarketQuote.quote_date == quote_date]
            if region:
                filters.append(MarketQuote.market_region == region)
            if asset_filter:
                filters.append(MarketQuote.asset_class.in_(asset_filter))
            stmt = (
                select(*_MARKET_QUOTE_COLS)
                .where(*filters)
                .order_by(MarketQuote.market_region, MarketQuote.symbol_code)
            )
            return [_row_to_market_quote(r) for r in session.execute(stmt).all()]

        # Per-symbol latest: correlated subquery
        latest_per_symbol = (
            select(
                MarketQuote.symbol_code,
                func.max(MarketQuote.quote_date).label("max_date"),
            )
            .group_by(MarketQuote.symbol_code)
            .subquery()
        )
        stmt = (
            select(*_MARKET_QUOTE_COLS)
            .join(
                latest_per_symbol,
                (MarketQuote.symbol_code == latest_per_symbol.c.symbol_code)
                & (MarketQuote.quote_date == latest_per_symbol.c.max_date),
            )
        )
        if region:
            stmt = stmt.where(MarketQuote.market_region == region)
        if asset_filter:
            stmt = stmt.where(MarketQuote.asset_class.in_(asset_filter))
        stmt = stmt.order_by(MarketQuote.market_region, MarketQuote.symbol_code)
        return [_row_to_market_quote(r) for r in session.execute(stmt).all()]


def distinct_market_dates(limit: int = 30) -> list[date]:
    """Distinct quote dates, most recent first."""
    with _session() as session:
        rows = session.execute(
            select(distinct(MarketQuote.quote_date))
            .order_by(MarketQuote.quote_date.desc())
            .limit(limit)
        ).all()
    return [r[0] for r in rows]


def latest_market_date() -> date | None:
    with _session() as session:
        return session.execute(
            select(func.max(MarketQuote.quote_date))
        ).scalar_one_or_none()


def market_quote_history(
    symbol_code: str,
    days: int = 30,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """Return a time series of (date, close) for a single symbol.

    Returns up to ``days`` records ending at ``end_date`` (inclusive); if
    ``end_date`` is None, falls back to the most recent record in the table.
    The result is sorted ascending so callers can chart it directly.

    Used to build Chart.js sparklines on the market dashboard and to draw the
    cluster-vs-market comparison chart on the similarity detail page.
    """
    with _session() as session:
        stmt = (
            select(MarketQuote.quote_date, MarketQuote.close_price)
            .where(MarketQuote.symbol_code == symbol_code)
        )
        if end_date is not None:
            stmt = stmt.where(MarketQuote.quote_date <= end_date)
        # Pull the latest ``days`` rows, then reverse to ascending order so
        # the chart's x-axis reads left-to-right.
        stmt = stmt.order_by(MarketQuote.quote_date.desc()).limit(days)
        rows_desc = list(session.execute(stmt).all())
    rows = list(reversed(rows_desc))
    return [
        {"date": r[0].isoformat(), "close": float(r[1]) if r[1] is not None else None}
        for r in rows
    ]


def market_quote_history_batch(
    symbol_codes: list[str],
    days: int = 30,
    end_date: date | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Batch variant of :func:`market_quote_history` for many symbols.

    Issues a single ``WHERE symbol_code IN (...)`` query instead of one per
    symbol. Each symbol's series is trimmed to the latest ``days`` records
    ending at ``end_date`` (inclusive) and returned in ascending order so
    callers can feed it directly into Chart.js.

    Args:
        symbol_codes: Symbol codes to fetch. Empty list returns an empty dict.
        days: Maximum number of records per symbol.
        end_date: Inclusive upper bound for the quote date. When ``None``,
            the most recent record in the table is used as the anchor.

    Returns:
        Mapping from ``symbol_code`` to a list of ``{date, close}`` dicts.
        Symbols with no matching records map to an empty list.
    """
    if not symbol_codes:
        return {}

    with _session() as session:
        stmt = (
            select(
                MarketQuote.symbol_code,
                MarketQuote.quote_date,
                MarketQuote.close_price,
            )
            .where(MarketQuote.symbol_code.in_(symbol_codes))
        )
        if end_date is not None:
            stmt = stmt.where(MarketQuote.quote_date <= end_date)
        # Pull rows in descending order so ``[:days]`` below naturally trims
        # to the most recent ``days`` records per symbol.
        stmt = stmt.order_by(
            MarketQuote.symbol_code,
            MarketQuote.quote_date.desc(),
        )
        rows = list(session.execute(stmt).all())

    by_symbol: dict[str, list[tuple[Any, Any]]] = {code: [] for code in symbol_codes}
    for sym_code, quote_date, close_price in rows:
        bucket = by_symbol.get(sym_code)
        if bucket is None:
            continue
        if len(bucket) >= days:
            continue
        bucket.append((quote_date, close_price))

    return {
        code: [
            {"date": d.isoformat(), "close": float(c) if c is not None else None}
            for d, c in reversed(items)
        ]
        for code, items in by_symbol.items()
    }


def market_summary() -> dict[str, Any]:
    """Aggregate snapshot for the dashboard market card."""
    with _session() as session:
        latest_date = session.execute(
            select(func.max(MarketQuote.quote_date))
        ).scalar_one_or_none()
        symbol_count = session.execute(
            select(func.count(distinct(MarketQuote.symbol_code)))
        ).scalar_one()
        by_region = session.execute(
            select(
                MarketQuote.market_region,
                func.count(MarketQuote.id),
            )
            .group_by(MarketQuote.market_region)
            .order_by(MarketQuote.market_region)
        ).all()
        # Per-symbol latest to show all indices even when some are stale.
        latest_quotes = list_market_quotes()

    return {
        "latest_date": latest_date,
        "symbol_count": symbol_count,
        "by_region": [{"region": r[0], "count": r[1]} for r in by_region],
        "latest_quotes": latest_quotes,
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def dashboard_summary() -> dict[str, Any]:
    with _session() as session:
        product_total: int = session.execute(
            select(func.count(ProductInfo.id))
        ).scalar_one()
        institution_total: int = session.execute(
            select(func.count(distinct(ProductInfo.institution_code)))
        ).scalar_one()
        nav_total: int = session.execute(
            select(func.count(ProductNav.id))
        ).scalar_one()

        # Holding stats ----------------------------------------------------
        holding_total: int = session.execute(
            select(func.count(ProductHolding.id))
        ).scalar_one()
        report_total: int = session.execute(
            select(func.count(HoldingReport.id))
        ).scalar_one()
        products_with_holding: int = session.execute(
            select(func.count(distinct(ProductHolding.product_id)))
        ).scalar_one()
        latest_holding_date: date | None = session.execute(
            select(func.max(ProductHolding.report_date))
        ).scalar_one()
        latest_holding_institution_codes = []
        if latest_holding_date is not None:
            latest_holding_institution_codes = [
                r[0]
                for r in session.execute(
                    select(distinct(ProductInfo.institution_code))
                    .join(ProductHolding, ProductHolding.product_id == ProductInfo.id)
                    .where(ProductHolding.report_date == latest_holding_date)
                    .order_by(ProductInfo.institution_code)
                ).all()
            ]
        holding_by_type = session.execute(
            select(
                ProductHolding.asset_type,
                func.count(ProductHolding.id),
            )
            .group_by(ProductHolding.asset_type)
            .order_by(ProductHolding.asset_type)
        ).all()
        holding_by_institution = session.execute(
            select(
                ProductInfo.institution_code,
                func.count(ProductHolding.id),
            )
            .join(ProductHolding, ProductHolding.product_id == ProductInfo.id)
            .group_by(ProductInfo.institution_code)
            .order_by(ProductInfo.institution_code)
        ).all()

        last_success = session.execute(
            select(CollectionLog)
            .where(CollectionLog.status == "success")
            .order_by(CollectionLog.end_time.desc())
            .limit(1)
        ).scalar_one_or_none()

        by_inst_type = session.execute(
            select(
                ProductInfo.institution_code,
                ProductInfo.product_type,
                func.count(ProductInfo.id),
            )
            .group_by(
                ProductInfo.institution_code,
                ProductInfo.product_type,
            )
            .order_by(
                ProductInfo.institution_code,
                ProductInfo.product_type,
            )
        ).all()

        recent_logs = list(
            session.execute(
                select(CollectionLog)
                .order_by(CollectionLog.start_time.desc())
                .limit(10)
            ).scalars()
        )

    return {
        "product_total": product_total,
        "institution_total": institution_total,
        "nav_total": nav_total,
        "holding_total": holding_total,
        "report_total": report_total,
        "products_with_holding": products_with_holding,
        "latest_holding_date": latest_holding_date,
        "latest_holding_institutions": latest_holding_institution_codes,
        "holding_by_type": [
            {"asset_type": r[0], "count": r[1]} for r in holding_by_type
        ],
        "holding_by_institution": [
            {"institution_code": r[0], "count": r[1]} for r in holding_by_institution
        ],
        "last_success_at": last_success.end_time if last_success else None,
        "last_success_job": last_success.job_name if last_success else None,
        "by_inst_type": [
            {"institution_code": r[0], "product_type": r[1], "count": r[2]}
            for r in by_inst_type
        ],
        "recent_logs": recent_logs,
    }


# ---------------------------------------------------------------------------
# Similarity analysis queries
# ---------------------------------------------------------------------------


def _infer_asset_market(asset_code: str | None) -> str:
    """Infer market region from asset code prefix.

    Mirrors the rules used by similarity/industry.py so the web overlay agrees
    with the clustering layer's market inference.
    """
    if not asset_code:
        return "UNKNOWN"
    code = str(asset_code).strip()
    if len(code) == 5 and code.isdigit():
        return "HK"
    if code.isalpha() and 1 <= len(code) <= 5:
        return "US"
    if code.startswith(("60", "68", "51", "52", "53")):
        return "SH"
    if code.startswith(("00", "30", "39", "12", "08")):
        return "SZ"
    if code.startswith(("8", "4", "43")):
        return "BJ"
    return "UNKNOWN"


def _market_region_to_bundle_key(market: str) -> str:
    """Map inferred market region to MARKET_INDEX_BUNDLES key."""
    if market in ("SH", "SZ", "BJ"):
        return "domestic"
    return market.lower()  # hk / us / commodity / unknown


def list_similarity_runs(
    *,
    algorithm: str | None = None,
    report_date: date | None = None,
    limit: int = 20,
) -> list[SimilarityRunRow]:
    """List persisted similarity runs, most recent first."""
    with _session() as session:
        stmt = select(SimilarityClusterRun).order_by(
            desc(SimilarityClusterRun.report_date),
            desc(SimilarityClusterRun.created_at),
        )
        if algorithm is not None:
            stmt = stmt.where(SimilarityClusterRun.algorithm == algorithm)
        if report_date is not None:
            stmt = stmt.where(SimilarityClusterRun.report_date == report_date)
        stmt = stmt.limit(limit)
        rows = session.scalars(stmt).all()
    return [
        SimilarityRunRow(
            cluster_run_id=r.id,
            report_date=r.report_date,
            algorithm=r.algorithm,
            k=r.k,
            product_type_filter=r.product_type_filter,
            n_products=r.n_products,
            n_features=r.n_features,
            silhouette=float(r.silhouette) if r.silhouette is not None else None,
            inertia=float(r.inertia) if r.inertia is not None else None,
            created_at=r.created_at,
        )
        for r in rows
    ]


def distinct_similarity_report_dates(limit: int = 12) -> list[date]:
    """Distinct report dates that have persisted similarity runs."""
    with _session() as session:
        rows = session.execute(
            select(distinct(SimilarityClusterRun.report_date))
            .order_by(SimilarityClusterRun.report_date.desc())
            .limit(limit)
        ).all()
    return [r[0] for r in rows]


def distinct_similarity_algorithms() -> list[str]:
    """Distinct algorithm identifiers present in persisted runs."""
    with _session() as session:
        rows = session.execute(
            select(distinct(SimilarityClusterRun.algorithm))
            .order_by(SimilarityClusterRun.algorithm)
        ).all()
    return [r[0] for r in rows]


def load_similarity_run(
    *,
    report_date: date,
    algorithm: str,
    k: int | None = None,
    product_type_filter: str | None = None,
) -> SimilarityRunDetail | None:
    """Resolve and load a run by its natural key."""
    with _session() as session:
        stmt = (
            select(SimilarityClusterRun)
            .where(
                SimilarityClusterRun.report_date == report_date,
                SimilarityClusterRun.algorithm == algorithm,
            )
            .order_by(desc(SimilarityClusterRun.created_at))
        )
        if k is not None:
            stmt = stmt.where(SimilarityClusterRun.k == k)
        if product_type_filter is not None:
            stmt = stmt.where(
                SimilarityClusterRun.product_type_filter == product_type_filter
            )
        run = session.scalars(stmt).first()
        if run is None:
            return None
        return _hydrate_run(session, run)


def get_similarity_run_by_id(cluster_run_id: int) -> SimilarityRunDetail | None:
    """Load a run by primary key."""
    with _session() as session:
        run = session.get(SimilarityClusterRun, cluster_run_id)
        if run is None:
            return None
        return _hydrate_run(session, run)


def _hydrate_run(session, run) -> SimilarityRunDetail:
    """Internal: turn a SimilarityClusterRun ORM instance into a SimilarityRunDetail."""
    cluster_rows = session.scalars(
        select(SimilarityCluster)
        .where(SimilarityCluster.cluster_run_id == run.id)
        .order_by(SimilarityCluster.cluster_id)
    ).all()
    member_rows = session.scalars(
        select(SimilarityClusterMember)
        .where(SimilarityClusterMember.cluster_run_id == run.id)
    ).all()

    member_product_ids = {m.product_id for m in member_rows}
    products_by_id: dict[int, ProductInfo] = {}
    if member_product_ids:
        products = session.scalars(
            select(ProductInfo).where(ProductInfo.id.in_(member_product_ids))
        ).all()
        products_by_id = {p.id: p for p in products}

    run_row = SimilarityRunRow(
        cluster_run_id=run.id,
        report_date=run.report_date,
        algorithm=run.algorithm,
        k=run.k,
        product_type_filter=run.product_type_filter,
        n_products=run.n_products,
        n_features=run.n_features,
        silhouette=float(run.silhouette) if run.silhouette is not None else None,
        inertia=float(run.inertia) if run.inertia is not None else None,
        created_at=run.created_at,
    )
    cluster_list = [
        SimilarityClusterRow(
            cluster_id=c.cluster_id,
            size=c.size,
            cluster_label=c.cluster_label,
            top_holdings=enrich_top_holdings_with_names(c.top_holdings or []),
            top_industries=c.top_industries or [],
            avg_hhi=float(c.avg_hhi) if c.avg_hhi is not None else None,
            avg_overlap=float(c.avg_overlap) if c.avg_overlap is not None else None,
            avg_overlap_raw=(
                float(c.avg_overlap_raw) if c.avg_overlap_raw is not None else None
            ),
            ac_share_dominance_ratio=(
                float(c.ac_share_dominance_ratio)
                if c.ac_share_dominance_ratio is not None
                else None
            ),
            institution_distribution=c.institution_distribution or {},
            representative_products=c.representative_products or [],
            representative_codes=c.representative_codes or [],
            representative_names=c.representative_names or [],
        )
        for c in cluster_rows
    ]
    member_list = [
        SimilarityMemberRow(
            product_id=m.product_id,
            institution_code=products_by_id[m.product_id].institution_code
            if m.product_id in products_by_id
            else "",
            product_code=products_by_id[m.product_id].product_code
            if m.product_id in products_by_id
            else "",
            product_name=products_by_id[m.product_id].product_name
            if m.product_id in products_by_id
            else "",
            product_type=products_by_id[m.product_id].product_type
            if m.product_id in products_by_id
            else "",
            cluster_id=m.cluster_id,
            distance_to_center=(
                float(m.distance_to_center)
                if m.distance_to_center is not None
                else None
            ),
        )
        for m in member_rows
    ]
    return SimilarityRunDetail(
        run=run_row,
        clusters=cluster_list,
        members=member_list,
    )


def list_similarity_members(
    *,
    cluster_run_id: int,
    cluster_id: int,
    limit: int = 200,
    sort: str = "distance",
) -> list[SimilarityMemberRow]:
    """Members of a single cluster within a run, optionally filtered."""
    # Resolve run via get_similarity_run_by_id so we reuse the same hydration.
    detail = get_similarity_run_by_id(cluster_run_id)
    if detail is None:
        return []
    members = [m for m in detail.members if m.cluster_id == cluster_id]
    if sort == "distance":
        members.sort(
            key=lambda m: (
                m.distance_to_center if m.distance_to_center is not None else 1e18
            )
        )
    elif sort == "institution":
        members.sort(key=lambda m: (m.institution_code, m.product_code))
    elif sort == "code":
        members.sort(key=lambda m: m.product_code)
    return members[:limit]


def cluster_market_overlay(
    *,
    top_holdings: list[dict[str, Any]],
    days: int = 60,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """Pick a market-index overlay for a cluster based on its actual asset mix.

    Returns a list of Chart.js dataset dicts:
    ``[{label, code, region, weight, data: [{date, close}, ...]}, ...]``.

    The selection always includes ``SH000300`` as a baseline domestic reference.
    If the cluster's top holdings include HK/US/A-share dominant weight, the
    corresponding bundles (HSI / NDX+SPX / CSI-300 / SZ399006) are added so
    the comparison is meaningful for that market exposure.

    Each dataset's series covers up to ``days`` records ending at ``end_date``
    (inclusive). Pass ``end_date = today - 1`` so market data — which usually
    lags one trading day — lines up with the page's view of "today".
    """
    market_weights: dict[str, float] = {}
    for h in top_holdings or []:
        code = h.get("asset_code")
        weight = float(h.get("weight") or 0.0)
        if not code or weight <= 0:
            continue
        region = _infer_asset_market(code)
        market_weights[region] = market_weights.get(region, 0.0) + weight

    codes: list[str] = list(MARKET_INDEX_BUNDLES["baseline"])

    # Pick the dominant non-UNKNOWN, non-baseline region if any.
    candidate_regions = {
        r: w for r, w in market_weights.items() if r not in ("UNKNOWN",)
    }
    if candidate_regions:
        dominant = max(candidate_regions, key=candidate_regions.get)
        bundle_key = _market_region_to_bundle_key(dominant)
        for code in MARKET_INDEX_BUNDLES.get(bundle_key, []):
            if code not in codes:
                codes.append(code)

    # If the cluster has *both* domestic and HK/US weight, also include the
    # alternate bundle for richer comparison (limit to one extra bundle).
    if any(r in candidate_regions for r in ("HK", "US")) and any(
        r in candidate_regions for r in ("SH", "SZ", "BJ")
    ):
        for code in MARKET_INDEX_BUNDLES["domestic"]:
            if code not in codes:
                codes.append(code)

    # Build Chart.js datasets using existing market data helpers.
    quotes_by_code = {q.symbol_code: q for q in list_market_quotes()}
    datasets: list[dict[str, Any]] = []
    for code in codes:
        quote = quotes_by_code.get(code)
        if quote is None:
            continue
        inferred = _infer_asset_market(code[:6])
        datasets.append(
            {
                "label": quote.symbol_name,
                "code": quote.symbol_code,
                "region": quote.market_region,
                "weight": float(market_weights.get(inferred, 0.0)),
                "data": market_quote_history(
                    quote.symbol_code, days=days, end_date=end_date
                ),
            }
        )
    return datasets


def cluster_market_breakdown(
    top_holdings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return ``[{market, weight}]`` for a cluster's holdings, sorted desc."""
    market_weights: dict[str, float] = {}
    for h in top_holdings or []:
        code = h.get("asset_code")
        weight = float(h.get("weight") or 0.0)
        if not code or weight <= 0:
            continue
        region = _infer_asset_market(code)
        market_weights[region] = market_weights.get(region, 0.0) + weight

    region_label = {
        "SH": "上海A股",
        "SZ": "深圳A股",
        "BJ": "北交所",
        "HK": "港股",
        "US": "美股",
        "UNKNOWN": "未识别",
    }
    items = [
        {"market": m, "label": region_label.get(m, m), "weight": w}
        for m, w in market_weights.items()
    ]
    items.sort(key=lambda x: x["weight"], reverse=True)
    return items


# ---------------------------------------------------------------------------
# Cluster labelling
# ---------------------------------------------------------------------------

# `derive_cluster_label` is shared with the similarity service and imported
# from ``fundseeker.similarity.labels`` at the top of this module. It is kept
# here as the canonical fallback used by the web layer when rendering runs
# whose persisted ``cluster_label`` is empty.


def enrich_top_holdings_with_names(
    top_holdings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach asset_name to each entry of top_holdings, looked up from
    ``holding_security_info`` (with fallbacks).
    """
    if not top_holdings:
        return []
    codes = [h.get("asset_code") for h in top_holdings if h.get("asset_code")]
    if not codes:
        return list(top_holdings)
    name_map: dict[str, str] = {}
    with _session() as session:
        rows = session.execute(
            select(
                HoldingSecurityInfo.asset_code,
                HoldingSecurityInfo.asset_name,
                HoldingSecurityInfo.market,
            )
            .where(HoldingSecurityInfo.asset_code.in_(codes))
        ).all()
    for code, name, market in rows:
        # Prefer the SH/SZ row; HK second; others last.
        priority = {"SH": 0, "SZ": 1, "BJ": 2, "HK": 3}.get(market, 4)
        prev = name_map.get(code)
        if prev is None:
            name_map[code] = (name, priority)
        else:
            # Stored as tuple (name, priority); keep the highest-priority name.
            _, prev_pri = prev
            if priority < prev_pri:
                name_map[code] = (name, priority)

    enriched = []
    for h in top_holdings:
        code = h.get("asset_code")
        entry = dict(h)
        if code and code in name_map:
            entry["asset_name"] = name_map[code][0]
        else:
            entry["asset_name"] = code or "—"
        enriched.append(entry)
    return enriched


def cluster_member_value_snapshot(
    *,
    cluster_run_id: int,
    cluster_id: int,
    days: int = 60,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """Return one row per cluster member with NAV data over a fixed window.

    The window is ``[end_date - days, end_date]`` where ``end_date`` defaults
    to *today minus one day* — the same convention the market chart uses,
    because market data and product NAV both lag one trading day behind the
    calendar.

    A "logical product" is ``(institution_code, product_code)`` and may span
    many ``product_info.id`` rows — one per ``collect_date`` — each with its
    own single NAV snapshot. To get a real period change we look up *all*
    ``product_info.id`` values for the same logical product, pull every NAV
    row in the window across those ids, and pick the latest and earliest
    snapshots. If only one row exists in the window we cannot compute a real
    period change so ``period_change_pct`` is ``None`` and the row is excluded
    from the dispersion ranking.

    Each row carries:
        ``{product_id, product_code, product_name, institution_code,
            product_type, latest_nav_date, latest_unit_nav,
            earliest_nav_date, earliest_unit_nav, span_days,
            period_change_pct, holding_market_value, holding_weight,
            window_start, window_end, nav_record_count}``
    """
    if end_date is None:
        end_date = date.today() - timedelta(days=1)
    window_start = end_date - timedelta(days=days)

    detail = get_similarity_run_by_id(cluster_run_id)
    if detail is None:
        return []
    run = detail.run
    members = [m for m in detail.members if m.cluster_id == cluster_id]

    member_product_ids = [m.product_id for m in members]
    if not member_product_ids:
        return []

    # Step 1: Resolve every cluster member's logical product key
    # (institution_code, product_code) and gather all sibling product_info.id
    # values that share it. The sibling ids are what carry the historical
    # NAV rows we're after.
    logical_to_member_pid: dict[tuple[str, str], int] = {}
    with _session() as session:
        rows = session.execute(
            select(ProductInfo.id, ProductInfo.institution_code, ProductInfo.product_code)
            .where(ProductInfo.id.in_(member_product_ids))
        ).all()
        for pid, inst, code in rows:
            logical_to_member_pid[(inst, code)] = pid

    if not logical_to_member_pid:
        return []

    with _session() as session:
        siblings_rows = session.execute(
            select(ProductInfo.id, ProductInfo.institution_code, ProductInfo.product_code)
            .where(
                ProductInfo.institution_code.in_(
                    [k[0] for k in logical_to_member_pid.keys()]
                ),
                ProductInfo.product_code.in_(
                    [k[1] for k in logical_to_member_pid.keys()]
                ),
            )
        ).all()
    # Map (inst, code) -> list of all sibling product_ids
    siblings_by_logical: dict[tuple[str, str], list[int]] = {}
    for pid, inst, code in siblings_rows:
        if (inst, code) in logical_to_member_pid:
            siblings_by_logical.setdefault((inst, code), []).append(pid)

    all_sibling_ids: list[int] = []
    for ids in siblings_by_logical.values():
        all_sibling_ids.extend(ids)

    # Step 2: Pull every NAV row for all sibling product_ids inside the window,
    # bucketed per logical product key.
    nav_by_logical: dict[tuple[str, str], list[tuple[date, float]]] = {}
    with _session() as session:
        nav_stmt = (
            select(
                ProductInfo.institution_code,
                ProductInfo.product_code,
                ProductNav.nav_date,
                ProductNav.unit_nav,
            )
            .join(ProductInfo, ProductInfo.id == ProductNav.product_id)
            .where(
                ProductNav.product_id.in_(all_sibling_ids),
                ProductNav.nav_date >= window_start,
                ProductNav.nav_date <= end_date,
            )
            .order_by(ProductNav.nav_date.asc())
        )
        for inst, code, ndate, unav in session.execute(nav_stmt).all():
            nav_by_logical.setdefault((inst, code), []).append(
                (ndate, float(unav))
            )

    # Step 3: Holding market value / weight — still keyed by the cluster
    # member's product_id (which is the snapshot id used at clustering time).
    mv_by_pid: dict[int, tuple[float, float]] = {}
    with _session() as session:
        mv_stmt = (
            select(
                ProductHolding.product_id,
                func.sum(ProductHolding.market_value),
                func.sum(ProductHolding.weight),
            )
            .where(
                ProductHolding.report_date == run.report_date,
                ProductHolding.product_id.in_(member_product_ids),
            )
            .group_by(ProductHolding.product_id)
        )
        for pid, mv, w in session.execute(mv_stmt).all():
            mv_by_pid[pid] = (float(mv or 0), float(w or 0))

    results: list[dict[str, Any]] = []
    for m in members:
        logical_key = (m.institution_code, m.product_code)
        rows = nav_by_logical.get(logical_key, [])
        # Dedupe same-date rows (different sibling product_ids may share a
        # nav_date when collection runs twice); keep the row whose value
        # matches the typical chain (i.e. any of them — they should agree).
        if rows:
            seen_dates: dict[date, float] = {}
            for d, v in rows:
                if d not in seen_dates:
                    seen_dates[d] = v
            sorted_rows = sorted(seen_dates.items())
            earliest_dt, earliest_nav = sorted_rows[0]
            latest_dt, latest_nav = sorted_rows[-1]
            span_days = (
                (latest_dt - earliest_dt).days
                if latest_dt != earliest_dt
                else None
            )
            nav_record_count = len(sorted_rows)
        else:
            latest_dt = latest_nav = earliest_dt = earliest_nav = None
            span_days = None
            nav_record_count = 0

        if (
            latest_nav is not None
            and earliest_nav is not None
            and earliest_nav != 0
            and latest_dt != earliest_dt
        ):
            period_change_pct = (latest_nav - earliest_nav) / earliest_nav
        else:
            # Zero or one NAV row inside the window: no real change to report.
            period_change_pct = None

        mv, total_w = mv_by_pid.get(m.product_id, (0.0, 0.0))
        results.append(
            {
                "product_id": m.product_id,
                "product_code": m.product_code,
                "product_name": m.product_name,
                "institution_code": m.institution_code,
                "product_type": m.product_type,
                "latest_nav_date": latest_dt,
                "latest_unit_nav": latest_nav,
                "earliest_nav_date": earliest_dt,
                "earliest_unit_nav": earliest_nav,
                "span_days": span_days,
                "nav_record_count": nav_record_count,
                "period_change_pct": period_change_pct,
                "window_start": window_start,
                "window_end": end_date,
                "holding_market_value": mv,
                "holding_weight": total_w,
            }
        )
    return results


def cluster_value_dispersion(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute dispersion statistics over a cluster's per-product NAV change.

    The metric of interest is the **period change percentage** of each
    product's unit NAV over the statistical window (e.g. 60 days), not the
    absolute NAV value. ``top5`` and ``bottom5`` therefore rank products by
    ``period_change_pct`` — the products whose NAV grew the most / least over
    the period.

    Returns:
        dict with: n, mean_change, std_change, min_change, max_change,
        median_change, coefficient_of_variation, range_pct, top5 (highest
        period_change_pct), bottom5 (lowest period_change_pct), as well as the
        latest NAV stats retained for backwards compatibility.
    """
    values = [
        float(r["period_change_pct"])
        for r in rows
        if r.get("period_change_pct") is not None
    ]
    n = len(values)
    if n == 0:
        return {
            "n": 0,
            "mean_change": None,
            "std_change": None,
            "min_change": None,
            "max_change": None,
            "median_change": None,
            "coefficient_of_variation": None,
            "range_pct": None,
            "positive_share": None,
            "top5": [],
            "bottom5": [],
            # Legacy fields (latest NAV) retained so older templates still work.
            "mean_nav": None,
            "min_nav": None,
            "max_nav": None,
        }

    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if n > 1 else 0.0
    median = float(np.median(arr))
    mn = float(arr.min())
    mx = float(arr.max())
    # Range as a percentage (max - min). For change percentages this is the
    # spread in percentage points, which is the most readable metric here.
    range_pp = mx - mn
    positive_share = float((arr > 0).mean()) if n else 0.0
    # Coefficient of variation over the change percentages themselves (the
    # std/mean ratio of % changes). Use abs(mean) to avoid sign flipping when
    # the cluster is mixed positive/negative.
    cv = std / abs(mean) if mean else 0.0

    sorted_rows = sorted(
        [r for r in rows if r.get("period_change_pct") is not None],
        key=lambda r: r["period_change_pct"],
        reverse=True,
    )
    top5 = sorted_rows[:5]
    bottom5 = sorted_rows[-5:][::-1]  # keep ascending order within bottom5

    # Legacy latest-NAV stats for callers that still want them.
    nav_values = [
        float(r["latest_unit_nav"])
        for r in rows
        if r.get("latest_unit_nav") is not None
    ]
    if nav_values:
        nav_arr = np.asarray(nav_values, dtype=float)
        mean_nav = float(nav_arr.mean())
        min_nav = float(nav_arr.min())
        max_nav = float(nav_arr.max())
    else:
        mean_nav = min_nav = max_nav = None

    return {
        "n": n,
        "mean_change": mean,
        "std_change": std,
        "min_change": mn,
        "max_change": mx,
        "median_change": median,
        "coefficient_of_variation": cv,
        "range_pct": range_pp,
        "positive_share": positive_share,
        "top5": top5,
        "bottom5": bottom5,
        "mean_nav": mean_nav,
        "min_nav": min_nav,
        "max_nav": max_nav,
    }


def _build_composite_series(
    rows: list[dict[str, Any]],
    days: int = 60,
    end_date: date | None = None,
) -> tuple[list[dict[str, Any]], date | None, float | None]:
    """Build a composite NAV time series and return its anchor metadata.

    The window is ``[end_date - days, end_date]`` (``end_date`` defaults to
    today minus one day so market and NAV data line up). Each cluster member
    is identified by ``(institution_code, product_code)`` (its logical
    product key) so every NAV row attached to any sibling ``product_info.id``
    counts as the same product. The composite at each date is the
    equal-weighted mean across members, rebased to 100 at the anchor date.

    Returns:
        A tuple of ``(series, anchor_date, anchor_value)``.
        ``series`` is ``[{date: ISO, close: float}]`` for Chart.js, with
        ``close`` rebased to 100 at the anchor date. ``anchor_value`` is the
        raw (unrebased) average NAV at the anchor date; it is ``None`` when
        the series could not be rebased (e.g. anchor value is zero).
    """
    if end_date is None:
        end_date = date.today() - timedelta(days=1)
    window_start = end_date - timedelta(days=days)

    # Collect the distinct logical products from the input rows.
    logical_keys: set[tuple[str, str]] = set()
    for r in rows:
        inst = r.get("institution_code")
        code = r.get("product_code")
        if inst and code:
            logical_keys.add((inst, code))
    if not logical_keys:
        return [], None, None

    # Resolve all sibling product_ids for each logical key.
    with _session() as session:
        sib_rows = session.execute(
            select(ProductInfo.id, ProductInfo.institution_code, ProductInfo.product_code)
            .where(
                ProductInfo.institution_code.in_([k[0] for k in logical_keys]),
                ProductInfo.product_code.in_([k[1] for k in logical_keys]),
            )
        ).all()
    sibling_ids_by_logical: dict[tuple[str, str], list[int]] = {}
    for pid, inst, code in sib_rows:
        if (inst, code) in logical_keys:
            sibling_ids_by_logical.setdefault((inst, code), []).append(pid)

    all_sibling_ids: list[int] = []
    for ids in sibling_ids_by_logical.values():
        all_sibling_ids.extend(ids)
    if not all_sibling_ids:
        return [], None, None

    # Pull every NAV row inside the window for these sibling product_ids.
    nav_by_pid: dict[int, list[tuple[date, float]]] = {}
    with _session() as session:
        nav_stmt = (
            select(
                ProductInfo.id,
                ProductInfo.institution_code,
                ProductInfo.product_code,
                ProductNav.nav_date,
                ProductNav.unit_nav,
            )
            .join(ProductInfo, ProductInfo.id == ProductNav.product_id)
            .where(
                ProductNav.product_id.in_(all_sibling_ids),
                ProductNav.nav_date >= window_start,
                ProductNav.nav_date <= end_date,
            )
            .order_by(ProductNav.nav_date.asc())
        )
        for pid, inst, code, ndate, unav in session.execute(nav_stmt).all():
            nav_by_pid.setdefault(pid, []).append((ndate, float(unav)))

    # Reduce sibling NAV rows to a single (date -> value) series per logical
    # product. When the same logical product has multiple sibling rows on the
    # same date, we keep the first one encountered (they should agree).
    series_by_logical: dict[tuple[str, str], dict[date, float]] = {
        k: {} for k in logical_keys
    }
    for (inst, code), ids in sibling_ids_by_logical.items():
        series = series_by_logical[(inst, code)]
        for pid in ids:
            for d, v in nav_by_pid.get(pid, []):
                if d not in series:
                    series[d] = v

    # Aggregate across logical products: at each date, equal-weight the
    # available members' NAVs and average.
    by_date: dict[date, list[float]] = {}
    for series in series_by_logical.values():
        for d, v in series.items():
            by_date.setdefault(d, []).append(v)

    if not by_date:
        return [], None, None

    # Anchor selection: pick the first date in the window where the
    # majority of cluster members (≥ 80%) are represented. Using the very
    # first date can introduce sampling bias when only a handful of products
    # happen to have a NAV that early (e.g. 6/29 has 44 of 100 products but
    # 6/30 has all 100).
    sorted_dates = sorted(by_date.keys())
    n_members = len(logical_keys)
    min_coverage = max(1, int(n_members * 0.8))
    anchor_date = next(
        (d for d in sorted_dates if len(by_date[d]) >= min_coverage),
        sorted_dates[0],
    )
    anchor_value = float(np.mean(by_date[anchor_date]))
    if not anchor_value:
        series = [
            {"date": d.isoformat(), "close": float(np.mean(by_date[d]))}
            for d in sorted_dates
        ]
        return series, anchor_date, None

    raw_series = [
        (d, float(np.mean(by_date[d])))
        for d in sorted_dates
    ]

    series = [
        {"date": d.isoformat(), "close": float(v / anchor_value * 100.0)}
        for d, v in raw_series
    ]
    return series, anchor_date, anchor_value


def cluster_composite_value_series(
    rows: list[dict[str, Any]],
    days: int = 60,
    end_date: date | None = None,
) -> list[dict[str, Any]]:
    """Build a composite NAV time series over a fixed window.

    Convenience wrapper around :func:`_build_composite_series` that returns
    only the chart-ready series. Values are rebased to 100 at the anchor date
    (first date with ≥ 80% member coverage).
    """
    series, _, _ = _build_composite_series(rows, days=days, end_date=end_date)
    return series


def cluster_composite_period_change(
    cluster_run_id: int,
    cluster_id: int,
    days: int = 60,
    end_date: date | None = None,
) -> dict[str, Any] | None:
    """Return the composite NAV period change for a single cluster.

    The change is measured from the composite's anchor date (rebased to 100)
    to the window end date. The anchor is the first date with ≥ 80% member
    coverage, which avoids sampling bias from the very first window date.

    Returns ``None`` if the composite series cannot be built. Otherwise returns
    a dict with ``start_date``, ``end_date``, ``start_value`` (rebased 100),
    ``end_value`` (rebased) and ``change_pct``.
    """
    rows = cluster_member_value_snapshot(
        cluster_run_id=cluster_run_id,
        cluster_id=cluster_id,
        days=days,
        end_date=end_date,
    )
    if not rows:
        return None
    series, anchor_date, anchor_value = _build_composite_series(
        rows, days=days, end_date=end_date
    )
    if len(series) < 2 or anchor_date is None:
        return None
    end = series[-1]
    end_value = float(end["close"])
    if anchor_value:
        # Rebased series: anchor = 100 by construction.
        start_value = 100.0
        change_pct = end_value / 100.0 - 1.0
    else:
        # Unrebased fallback (anchor value was zero): use first point.
        start = series[0]
        start_value = float(start["close"])
        change_pct = (
            (end_value / start_value - 1.0) if start_value else None
        )
    return {
        "start_date": anchor_date.isoformat(),
        "end_date": end["date"],
        "start_value": start_value,
        "end_value": end_value,
        "change_pct": change_pct,
    }


def cluster_run_period_changes(
    cluster_run_id: int,
    days: int = 60,
    end_date: date | None = None,
) -> dict[int, dict[str, Any]]:
    """Compute composite NAV period changes for every cluster in a run.

    Loads the run detail once and delegates per-cluster calculation to
    :func:`cluster_composite_period_change` so the run overview page can
    display each cluster's recent market movement.

    Returns:
        Mapping ``cluster_id -> {start_date, end_date, start_value, end_value, change_pct}``.
        Clusters without enough NAV data are omitted.
    """
    detail = get_similarity_run_by_id(cluster_run_id)
    if detail is None:
        return {}
    if end_date is None:
        end_date = date.today() - timedelta(days=1)

    result: dict[int, dict[str, Any]] = {}
    for cluster in detail.clusters:
        change = cluster_composite_period_change(
            cluster_run_id=cluster_run_id,
            cluster_id=cluster.cluster_id,
            days=days,
            end_date=end_date,
        )
        if change is not None:
            result[cluster.cluster_id] = change
    return result


def cluster_distance_histogram(
    member_distances: list[float | None],
    n_bins: int = 10,
) -> list[dict[str, Any]]:
    """Bin a list of (possibly None) distances into ``n_bins`` equal-width bins."""
    values = [float(v) for v in member_distances if v is not None]
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [{"bin": f"{lo:.3f}", "count": len(values)}]
    step = (hi - lo) / n_bins
    bins: list[dict[str, Any]] = [
        {
            "lo": lo + i * step,
            "hi": lo + (i + 1) * step,
            "count": 0,
        }
        for i in range(n_bins)
    ]
    for v in values:
        idx = min(int((v - lo) / step), n_bins - 1)
        bins[idx]["count"] += 1
    return [
        {"bin": f"{b['lo']:.3f}-{b['hi']:.3f}", "count": b["count"]}
        for b in bins
    ]


def list_product_cluster_memberships(
    product_id: int,
) -> list[dict[str, Any]]:
    """Return all cluster memberships for a given product across runs.

    Each entry contains run metadata + cluster size + distance + top_industries
    of the cluster the product was placed in.
    """
    with _session() as session:
        member_rows = session.execute(
            select(SimilarityClusterMember, SimilarityClusterRun, SimilarityCluster)
            .join(
                SimilarityClusterRun,
                SimilarityClusterMember.cluster_run_id == SimilarityClusterRun.id,
            )
            .join(
                SimilarityCluster,
                (SimilarityCluster.cluster_run_id == SimilarityClusterMember.cluster_run_id)
                & (SimilarityCluster.cluster_id == SimilarityClusterMember.cluster_id),
            )
            .where(SimilarityClusterMember.product_id == product_id)
            .order_by(
                desc(SimilarityClusterRun.report_date),
                desc(SimilarityClusterRun.created_at),
            )
        ).all()

        results: list[dict[str, Any]] = []
        for member, run, cluster in member_rows:
            results.append(
                {
                    "cluster_run_id": run.id,
                    "report_date": run.report_date,
                    "algorithm": run.algorithm,
                    "k": run.k,
                    "product_type_filter": run.product_type_filter,
                    "cluster_id": member.cluster_id,
                    "cluster_size": cluster.size,
                    "distance_to_center": (
                        float(member.distance_to_center)
                        if member.distance_to_center is not None
                        else None
                    ),
                    "top_industries": cluster.top_industries or [],
                }
            )
    return results
