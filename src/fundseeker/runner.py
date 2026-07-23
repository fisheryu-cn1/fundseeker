"""Reusable collection runners and reporting for FundSeeker.

This module exposes high-level functions that can be invoked either by the
standalone per-task scripts or by the unified ``fundseeker_cli.py`` entry
point. All functions return structured results suitable for generating a
post-run summary report.
"""

from __future__ import annotations

import concurrent.futures
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert

from fundseeker.collectors.bocwm import BOCWMCollector
from fundseeker.collectors.ccbwm import CCBWMCollector
from fundseeker.collectors.cebwm import CEBWMCollector
from fundseeker.collectors.chinaamc import ChinaAMCCollector
from fundseeker.collectors.cmbwm import CMBWMCollector
from fundseeker.collectors.citicwm import CITICWMCollector
from fundseeker.collectors.eastmoney_holding import EastmoneyFundHoldingCollector
from fundseeker.collectors.efunds import EFundCollector
from fundseeker.collectors.gffunds import GFFundCollector
from fundseeker.collectors.htfund import HTFundCollector
from fundseeker.collectors.market_quote import MarketQuoteCollector
from fundseeker.collectors.spdbwm import SPDBWMCollector
from fundseeker.config import load_config
from fundseeker.models.database import get_engine, get_session_maker
from fundseeker.models.tables import (
    CollectionLog,
    HoldingReport,
    HoldingSecurityInfo,
    MarketQuote,
    ProductAssetAllocation,
    ProductHolding,
    ProductHoldingSummary,
    ProductInfo,
    ProductNav,
)


@dataclass
class TaskResult:
    """Result of a single collection task."""

    task_name: str
    institution_code: str | None
    status: str  # success / failed / skipped
    records_count: int = 0
    inserted: int = 0
    skipped: int = 0
    error_message: str | None = None
    duration_seconds: float = 0.0


@dataclass
class CollectionSummary:
    """Aggregated report produced after collection tasks finish."""

    run_at: datetime
    tasks: list[TaskResult] = field(default_factory=list)
    product_total: int = 0
    product_with_nav: int = 0
    product_with_holding: int = 0
    nav_total: int = 0
    holding_total: int = 0
    market_quote_total: int = 0
    market_quote_latest_date: date | None = None
    market_quote_symbol_count: int = 0
    latest_collect_date: date | None = None
    failed_tasks: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fund company runner
# ---------------------------------------------------------------------------

FUND_COLLECTORS = {
    "YFD": EFundCollector,
    "HTF": HTFundCollector,
    "GF": GFFundCollector,
    "ChinaAMC": ChinaAMCCollector,
}


def run_fund_company(
    code: str,
    config: dict[str, Any] | None = None,
    check_existing: bool = True,
) -> TaskResult:
    """Collect product list and latest NAV for a fund company."""
    if config is None:
        config = load_config()

    collector_cls = FUND_COLLECTORS[code]
    collector = collector_cls(config)
    engine = get_engine()
    Session = get_session_maker(engine)
    session = Session()

    start = datetime.now(timezone.utc)
    today = collector.today()

    if check_existing:
        existing = session.query(ProductInfo.id).filter(
            ProductInfo.institution_code == collector.institution_code,
            ProductInfo.collect_date == today,
        ).first()
        if existing is not None:
            session.close()
            return TaskResult(
                task_name=f"fund_company:{code}",
                institution_code=code,
                status="skipped",
                records_count=0,
                duration_seconds=0.0,
            )

    log = CollectionLog(
        job_name=f"{collector.institution_code.lower()}_product_list",
        institution_code=collector.institution_code,
        start_time=start,
        status="running",
    )
    session.add(log)
    session.commit()

    try:
        raw_items = collector.collect_product_list()
        normalized = collector.normalize(raw_items)

        inserted_info = 0
        skipped_info = 0
        for item in normalized:
            stmt = (
                insert(ProductInfo)
                .values(**item)
                .on_conflict_do_nothing(
                    index_elements=[
                        "institution_code",
                        "product_code",
                        "collect_date",
                    ]
                )
            )
            result = session.execute(stmt)
            if result.rowcount:
                inserted_info += 1
            else:
                skipped_info += 1
        session.commit()

        id_map = {
            (r.institution_code, r.product_code): r.id
            for r in session.query(ProductInfo).filter(
                ProductInfo.institution_code == collector.institution_code,
                ProductInfo.collect_date == today,
            )
        }

        inserted_nav = 0
        for raw in raw_items:
            product_code = raw.get("product_code")
            product_id = id_map.get((collector.institution_code, product_code))
            if product_id is None:
                continue
            unit_nav = collector._to_float(str(raw.get("unit_nav") or ""))
            if unit_nav is None:
                continue
            stmt = (
                insert(ProductNav)
                .values(
                    product_id=product_id,
                    nav_date=today,
                    unit_nav=unit_nav,
                    cumulative_nav=collector._to_float(
                        str(raw.get("cumulative_nav") or "")
                    ),
                    daily_return=collector._to_float(
                        str(raw.get("daily_return") or "")
                    ),
                    nav_type="normal",
                )
                .on_conflict_do_nothing(index_elements=["product_id", "nav_date"])
            )
            result = session.execute(stmt)
            if result.rowcount:
                inserted_nav += 1
        session.commit()

        log.end_time = datetime.now(timezone.utc)
        log.status = "success"
        log.records_count = inserted_info + inserted_nav
        session.commit()

        end = datetime.now(timezone.utc)
        duration = (end - start).total_seconds()
        return TaskResult(
            task_name=f"fund_company:{code}",
            institution_code=code,
            status="success",
            records_count=inserted_info + inserted_nav,
            inserted=inserted_info,
            skipped=skipped_info,
            duration_seconds=duration,
        )

    except Exception as exc:
        session.rollback()
        end = datetime.now(timezone.utc)
        log.end_time = end
        log.status = "failed"
        log.error_message = str(exc)
        session.commit()
        duration = (end - start).total_seconds()
        return TaskResult(
            task_name=f"fund_company:{code}",
            institution_code=code,
            status="failed",
            error_message=str(exc),
            duration_seconds=duration,
        )

    finally:
        session.close()


# ---------------------------------------------------------------------------
# Bank wealth management runner
# ---------------------------------------------------------------------------

BANK_WM_COLLECTORS = {
    "JX": CCBWMCollector,
    "ZY": CMBWMCollector,
    "BOC": BOCWMCollector,
    "SPD": SPDBWMCollector,
    "CITIC": CITICWMCollector,
    "CEB": CEBWMCollector,
}


def run_bank_wm(
    code: str,
    config: dict[str, Any] | None = None,
    check_existing: bool = True,
) -> TaskResult:
    """Collect product list and latest NAV for a bank wealth manager."""
    if config is None:
        config = load_config()

    collector_cls = BANK_WM_COLLECTORS[code]
    collector = collector_cls(config)
    engine = get_engine()
    Session = get_session_maker(engine)
    session = Session()

    start = datetime.now(timezone.utc)
    today = collector.today()

    if check_existing:
        existing = session.query(ProductInfo.id).filter(
            ProductInfo.institution_code == collector.institution_code,
            ProductInfo.collect_date == today,
        ).first()
        if existing is not None:
            session.close()
            return TaskResult(
                task_name=f"bank_wm:{code}",
                institution_code=code,
                status="skipped",
                records_count=0,
                duration_seconds=0.0,
            )

    log = CollectionLog(
        job_name=f"{collector.institution_code.lower()}_product_list",
        institution_code=collector.institution_code,
        start_time=start,
        status="running",
    )
    session.add(log)
    session.commit()

    try:
        raw_items = collector.collect_product_list()
        normalized = collector.normalize(raw_items)

        inserted_info = 0
        skipped_info = 0
        for item in normalized:
            stmt = (
                insert(ProductInfo)
                .values(**item)
                .on_conflict_do_nothing(
                    index_elements=[
                        "institution_code",
                        "product_code",
                        "collect_date",
                    ]
                )
            )
            result = session.execute(stmt)
            if result.rowcount:
                inserted_info += 1
            else:
                skipped_info += 1
        session.commit()

        id_map = {
            (r.institution_code, r.product_code): r.id
            for r in session.query(ProductInfo).filter(
                ProductInfo.institution_code == collector.institution_code,
                ProductInfo.collect_date == today,
            )
        }

        inserted_nav = 0
        for raw in raw_items:
            product_code = raw.get("product_code")
            product_id = id_map.get((collector.institution_code, product_code))
            if product_id is None:
                continue
            unit_nav = collector._to_float(str(raw.get("unit_nav") or ""))
            if unit_nav is None:
                continue
            stmt = (
                insert(ProductNav)
                .values(
                    product_id=product_id,
                    nav_date=raw.get("nav_date") or today,
                    unit_nav=unit_nav,
                    cumulative_nav=collector._to_float(
                        str(raw.get("cumulative_nav") or "")
                    ),
                    daily_return=None,
                    nav_type="normal",
                )
                .on_conflict_do_nothing(index_elements=["product_id", "nav_date"])
            )
            result = session.execute(stmt)
            if result.rowcount:
                inserted_nav += 1
        session.commit()

        log.end_time = datetime.now(timezone.utc)
        log.status = "success"
        log.records_count = inserted_info + inserted_nav
        session.commit()

        end = datetime.now(timezone.utc)
        duration = (end - start).total_seconds()
        return TaskResult(
            task_name=f"bank_wm:{code}",
            institution_code=code,
            status="success",
            records_count=inserted_info + inserted_nav,
            inserted=inserted_info,
            skipped=skipped_info,
            duration_seconds=duration,
        )

    except Exception as exc:
        session.rollback()
        end = datetime.now(timezone.utc)
        log.end_time = end
        log.status = "failed"
        log.error_message = str(exc)
        session.commit()
        duration = (end - start).total_seconds()
        return TaskResult(
            task_name=f"bank_wm:{code}",
            institution_code=code,
            status="failed",
            error_message=str(exc),
            duration_seconds=duration,
        )

    finally:
        session.close()


# ---------------------------------------------------------------------------
# Holding collection runner
# ---------------------------------------------------------------------------


def _ensure_security(session, row: dict[str, Any]) -> None:
    """Insert a security reference row if asset_code is present."""
    code = row.get("asset_code")
    if not code:
        return
    market = row.get("market") or "UNKNOWN"
    stmt = (
        insert(HoldingSecurityInfo)
        .values(
            asset_code=code,
            market=market,
            asset_name=row.get("asset_name"),
            asset_type=row.get("asset_type"),
            industry_name=row.get("industry_name"),
            issuer_name=row.get("issuer_name"),
        )
        .on_conflict_do_nothing(index_elements=["asset_code", "market"])
    )
    session.execute(stmt)


def _close_stale_collection_logs(session, stale_minutes: int = 30) -> int:
    """Mark long-running collection logs as failed to recover from crashes.

    When a collector process is killed or hangs without updating the log row,
    subsequent runs would otherwise see the job as already running. This helper
    closes any ``running`` log whose start_time is older than the threshold.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    stmt = (
        CollectionLog.__table__.update()
        .where(
            CollectionLog.status == "running",
            CollectionLog.start_time < cutoff,
        )
        .values(
            status="failed",
            end_time=datetime.now(timezone.utc),
            error_message="marked stale by runner startup",
        )
    )
    result = session.execute(stmt)
    session.commit()
    return result.rowcount


def _call_with_timeout(func, timeout: float, *args, **kwargs) -> Any:
    """Run ``func`` in a single worker thread with a hard timeout.

    This is a second line of defence: even if the HTTP library's timeout does
    not fire (e.g. a silent connection drop that TCP keepalive has not yet
    detected), the runner will not block forever on a single product.

    Note: we explicitly ``shutdown(wait=False)`` so that a hung worker thread
    does not delay the main loop while it waits for a dead socket to close.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        # cancel_futures requires Python 3.9+; fall back gracefully.
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            executor.shutdown(wait=False)
        raise TimeoutError(
            f"Collector call timed out after {timeout}s"
        ) from exc
    finally:
        # If we returned normally, the worker has finished; shut down without
        # blocking the main thread.
        if future.done():
            executor.shutdown(wait=False)


def run_holdings(
    institution_code: str | None = None,
    years: int = 1,
    skip_existing: bool = True,
    config: dict[str, Any] | None = None,
) -> TaskResult:
    """Collect portfolio holdings for fund-company products."""
    if config is None:
        config = load_config()

    collector = EastmoneyFundHoldingCollector(config)
    engine = get_engine()
    Session = get_session_maker(engine)
    session = Session()

    # Recover from previously crashed or hung holding collection runs.
    stale_log_minutes = int(
        config.get("global", {}).get("stale_log_minutes", 30)
    )
    stale_closed = _close_stale_collection_logs(
        session, stale_minutes=stale_log_minutes
    )
    if stale_closed:
        logging.warning("Marked %d stale collection_log rows as failed", stale_closed)

    start = datetime.now(timezone.utc)
    log = CollectionLog(
        job_name="eastmoney_fund_holding",
        institution_code=institution_code,
        start_time=start,
        status="running",
    )
    session.add(log)
    session.commit()

    try:
        subq = (
            session.query(
                ProductInfo.institution_code,
                ProductInfo.product_code,
                func.max(ProductInfo.collect_date).label("max_collect_date"),
            )
            .filter(ProductInfo.institution_type == "fund_company")
            .group_by(ProductInfo.institution_code, ProductInfo.product_code)
            .subquery()
        )

        query = (
            session.query(ProductInfo)
            .join(
                subq,
                (ProductInfo.institution_code == subq.c.institution_code)
                & (ProductInfo.product_code == subq.c.product_code)
                & (ProductInfo.collect_date == subq.c.max_collect_date),
            )
            .order_by(ProductInfo.institution_code, ProductInfo.product_code)
        )
        if institution_code:
            query = query.filter(ProductInfo.institution_code == institution_code)
        if skip_existing:
            # Only skip products that already have a report for the latest
            # report date present in the database. Holding reports are
            # quarterly; once a product has the newest known quarter it should
            # not be re-fetched until a newer quarter is discovered.
            latest_report_date = (
                session.query(func.max(HoldingReport.report_date)).scalar()
            )
            if latest_report_date is not None:
                reported_ids = {
                    r[0]
                    for r in session.query(HoldingReport.product_id)
                    .filter(HoldingReport.report_date == latest_report_date)
                    .distinct()
                    .all()
                }
                query = query.filter(~ProductInfo.id.in_(reported_ids))

        products = query.all()

        reports_inserted = 0
        holdings_inserted = 0
        allocations_inserted = 0
        summaries_inserted = 0
        skipped_products = 0
        timed_out_products = 0

        # Guard against a single hung request stalling the entire batch. The
        # HTTP client already uses connect/read timeouts; this is a hard ceiling
        # for the whole collect_holdings call (including retries and delays).
        per_product_timeout = float(
            config.get("global", {}).get("holding_per_product_timeout_seconds", 90.0)
        )
        max_runtime_seconds = float(
            config.get("global", {}).get("max_runtime_seconds", 3600.0)
        )
        batch_deadline = start + timedelta(seconds=max_runtime_seconds)

        for product in products:
            if datetime.now(timezone.utc) > batch_deadline:
                logging.warning(
                    "Holding collection reached max_runtime_seconds=%s; stopping batch.",
                    max_runtime_seconds,
                )
                break

            try:
                result = _call_with_timeout(
                    collector.collect_holdings,
                    per_product_timeout,
                    product_code=product.product_code,
                    product_name=product.product_name,
                    years=years,
                )
            except TimeoutError as exc:
                logging.warning(
                    "Timeout collecting holdings for %s: %s", product.product_code, exc
                )
                # A hung connection may still be alive in the worker thread.
                # Reset the collector's session so the next product does not
                # wait on a dead connection from the pool.
                try:
                    collector.http.reset_session()
                except Exception:
                    logging.exception("Failed to reset HTTP session after timeout")
                timed_out_products += 1
                skipped_products += 1
                continue
            except Exception:
                logging.exception(
                    "Failed to collect holdings for %s", product.product_code
                )
                skipped_products += 1
                continue

            holdings = result.get("holdings", [])
            if not holdings:
                skipped_products += 1
                continue

            report_date = result.get("report_date")
            if report_date is None:
                skipped_products += 1
                continue

            stmt = (
                insert(HoldingReport)
                .values(
                    product_id=product.id,
                    report_date=report_date,
                    report_type=result.get("report_type", "quarterly"),
                    report_period=result.get("report_period"),
                    data_source=result.get("data_source", collector.source_url),
                )
                .on_conflict_do_nothing(
                    index_elements=["product_id", "report_date", "report_type"]
                )
            )
            session.execute(stmt)
            session.commit()

            report = (
                session.query(HoldingReport)
                .filter(
                    HoldingReport.product_id == product.id,
                    HoldingReport.report_date == report_date,
                    HoldingReport.report_type
                    == result.get("report_type", "quarterly"),
                )
                .first()
            )
            if report is None:
                skipped_products += 1
                continue

            reports_inserted += 1

            for row in holdings:
                _ensure_security(session, row)
                row_report_date = row.get("report_date", report_date)
                stmt = (
                    insert(ProductHolding)
                    .values(
                        report_id=report.id,
                        product_id=product.id,
                        report_date=row_report_date,
                        asset_code=row.get("asset_code"),
                        asset_name=row.get("asset_name", ""),
                        asset_type=row.get("asset_type", "other"),
                        sub_type=row.get("sub_type"),
                        market=row.get("market"),
                        issuer_name=row.get("issuer_name"),
                        industry_code=row.get("industry_code"),
                        industry_name=row.get("industry_name"),
                        weight=row.get("weight"),
                        market_value=row.get("market_value"),
                        share_quantity=row.get("share_quantity"),
                        cost_basis=row.get("cost_basis"),
                        valuation_method=row.get("valuation_method"),
                        is_top10=row.get("is_top10", False),
                        sort_order=row.get("sort_order"),
                    )
                    .on_conflict_do_nothing(
                        index_elements=["report_id", "asset_code", "asset_name"]
                    )
                )
                r = session.execute(stmt)
                if r.rowcount:
                    holdings_inserted += 1

            for alloc in result.get("asset_allocation", []):
                stmt = (
                    insert(ProductAssetAllocation)
                    .values(
                        report_id=report.id,
                        product_id=product.id,
                        report_date=report_date,
                        asset_class=alloc.get("asset_class", "other"),
                        weight=alloc.get("weight"),
                        market_value=alloc.get("market_value"),
                    )
                    .on_conflict_do_nothing(
                        index_elements=["report_id", "asset_class"]
                    )
                )
                r = session.execute(stmt)
                if r.rowcount:
                    allocations_inserted += 1

            summary = result.get("summary", {})
            stmt = (
                insert(ProductHoldingSummary)
                .values(
                    report_id=report.id,
                    product_id=product.id,
                    report_date=report_date,
                    top10_weight=summary.get("top10_weight"),
                    stock_weight=summary.get("stock_weight"),
                    bond_weight=summary.get("bond_weight"),
                    cash_weight=summary.get("cash_weight"),
                    fund_weight=summary.get("fund_weight"),
                    derivative_weight=summary.get("derivative_weight"),
                    non_standard_weight=summary.get("non_standard_weight"),
                    other_weight=summary.get("other_weight"),
                    concentration_score=summary.get("concentration_score"),
                    holding_count=summary.get("holding_count"),
                    turnover_indicator=summary.get("turnover_indicator"),
                )
                .on_conflict_do_nothing(
                    index_elements=["product_id", "report_date"]
                )
            )
            r = session.execute(stmt)
            if r.rowcount:
                summaries_inserted += 1

            session.commit()

        end = datetime.now(timezone.utc)
        log.end_time = end
        log.status = "success"
        log.records_count = (
            reports_inserted
            + holdings_inserted
            + allocations_inserted
            + summaries_inserted
        )
        session.commit()

        duration = (end - start).total_seconds()
        summary_message = None
        if timed_out_products:
            summary_message = f"{timed_out_products} products timed out (>{per_product_timeout}s)"
        return TaskResult(
            task_name=f"holdings:{institution_code or 'all'}",
            institution_code=institution_code,
            status="success",
            records_count=log.records_count,
            inserted=reports_inserted,
            skipped=skipped_products,
            error_message=summary_message,
            duration_seconds=duration,
        )

    except Exception as exc:
        session.rollback()
        end = datetime.now(timezone.utc)
        log.end_time = end
        log.status = "failed"
        log.error_message = str(exc)
        session.commit()
        duration = (end - start).total_seconds()
        return TaskResult(
            task_name=f"holdings:{institution_code or 'all'}",
            institution_code=institution_code,
            status="failed",
            error_message=str(exc),
            duration_seconds=duration,
        )

    finally:
        session.close()


# ---------------------------------------------------------------------------
# Market quote runner
# ---------------------------------------------------------------------------


def _parse_market_date(value: date | str | None) -> date:
    """Normalize a market quote target date."""
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def run_market_quotes(
    target_date: date | str | None = None,
    check_existing: bool = True,
    force: bool = False,
    config: dict[str, Any] | None = None,
) -> TaskResult:
    """Collect daily market quotes for major indices and commodities."""
    from datetime import timedelta

    if config is None:
        config = load_config()

    collector = MarketQuoteCollector(config)
    engine = get_engine()
    Session = get_session_maker(engine)
    session = Session()

    start = datetime.now(timezone.utc)
    expected_symbols = {s["symbol_code"] for s in collector.all_symbols}

    # Pre-check to avoid unnecessary network requests.
    if check_existing and not force:
        if target_date is not None:
            quote_date = _parse_market_date(target_date)
            existing = {
                r[0]
                for r in session.query(MarketQuote.symbol_code)
                .filter(MarketQuote.quote_date == quote_date)
                .all()
            }
            if expected_symbols.issubset(existing):
                session.close()
                return TaskResult(
                    task_name="market_quote",
                    institution_code=None,
                    status="skipped",
                    records_count=0,
                    duration_seconds=0.0,
                )
        else:
            # For "latest" collection, skip if every configured symbol already
            # has a row within the last 2 calendar days.
            recent_start = date.today() - timedelta(days=2)
            recent_rows = (
                session.query(MarketQuote.symbol_code)
                .filter(MarketQuote.quote_date >= recent_start)
                .distinct()
                .all()
            )
            if expected_symbols.issubset({r[0] for r in recent_rows}):
                session.close()
                return TaskResult(
                    task_name="market_quote",
                    institution_code=None,
                    status="skipped",
                    records_count=0,
                    duration_seconds=0.0,
                )

    log = CollectionLog(
        job_name="market_quote",
        institution_code=None,
        start_time=start,
        status="running",
    )
    session.add(log)
    session.commit()

    try:
        quotes = collector.collect(target_date=target_date)
        inserted = 0
        skipped = 0
        for q in quotes:
            stmt = (
                insert(MarketQuote)
                .values(**q)
                .on_conflict_do_nothing(
                    index_elements=["quote_date", "symbol_code"]
                )
            )
            result = session.execute(stmt)
            if result.rowcount:
                inserted += 1
            else:
                skipped += 1
        session.commit()

        log.end_time = datetime.now(timezone.utc)
        log.status = "success"
        log.records_count = inserted
        session.commit()

        end = datetime.now(timezone.utc)
        duration = (end - start).total_seconds()
        return TaskResult(
            task_name="market_quote",
            institution_code=None,
            status="success",
            records_count=inserted,
            inserted=inserted,
            skipped=skipped,
            duration_seconds=duration,
        )

    except Exception as exc:
        session.rollback()
        end = datetime.now(timezone.utc)
        log.end_time = end
        log.status = "failed"
        log.error_message = str(exc)
        session.commit()
        duration = (end - start).total_seconds()
        return TaskResult(
            task_name="market_quote",
            institution_code=None,
            status="failed",
            error_message=str(exc),
            duration_seconds=duration,
        )

    finally:
        session.close()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def build_summary(tasks: list[TaskResult]) -> CollectionSummary:
    """Query the database and build a human-readable collection summary."""
    engine = get_engine()
    summary = CollectionSummary(run_at=datetime.now(timezone.utc))
    summary.tasks = tasks

    with engine.connect() as conn:
        # Overall counts
        row = conn.execute(
            text(
                """
                SELECT
                    (SELECT COUNT(DISTINCT institution_code || ':' || product_code) FROM product_info) AS product_total,
                    (SELECT COUNT(DISTINCT p.institution_code || ':' || p.product_code)
                     FROM product_nav n JOIN product_info p ON p.id = n.product_id) AS product_with_nav,
                    (SELECT COUNT(DISTINCT p.institution_code || ':' || p.product_code)
                     FROM holding_report h JOIN product_info p ON p.id = h.product_id) AS product_with_holding,
                    (SELECT COUNT(*) FROM product_nav) AS nav_total,
                    (SELECT COUNT(*) FROM product_holding) AS holding_total,
                    (SELECT MAX(collect_date) FROM product_info) AS latest_collect_date,
                    (SELECT COUNT(*) FROM market_quote) AS market_quote_total,
                    (SELECT MAX(quote_date) FROM market_quote) AS market_quote_latest_date,
                    (SELECT COUNT(DISTINCT symbol_code) FROM market_quote WHERE quote_date >= CURRENT_DATE - INTERVAL '2 days') AS market_quote_symbol_count
                """
            )
        ).fetchone()
        summary.product_total = row.product_total
        summary.product_with_nav = row.product_with_nav
        summary.product_with_holding = row.product_with_holding
        summary.nav_total = row.nav_total
        summary.holding_total = row.holding_total
        summary.latest_collect_date = row.latest_collect_date
        summary.market_quote_total = row.market_quote_total
        summary.market_quote_latest_date = row.market_quote_latest_date
        summary.market_quote_symbol_count = row.market_quote_symbol_count

        # Per-institution coverage
        # Holdings and NAV are attached to a specific product snapshot, but they
        # logically belong to the product (institution_code, product_code). Join
        # across all snapshots so coverage is not lost when a new daily snapshot
        # is created.
        rows = conn.execute(
            text(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (institution_code, product_code)
                        id, institution_code, product_code
                    FROM product_info
                    ORDER BY institution_code, product_code, collect_date DESC
                ),
                nav_products AS (
                    SELECT DISTINCT p.institution_code, p.product_code
                    FROM product_nav n
                    JOIN product_info p ON p.id = n.product_id
                ),
                holding_products AS (
                    SELECT DISTINCT p.institution_code, p.product_code
                    FROM holding_report h
                    JOIN product_info p ON p.id = h.product_id
                )
                SELECT
                    l.institution_code,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE np.product_code IS NOT NULL) AS with_nav,
                    COUNT(*) FILTER (WHERE hp.product_code IS NOT NULL) AS with_holding
                FROM latest l
                LEFT JOIN nav_products np
                    ON np.institution_code = l.institution_code
                    AND np.product_code = l.product_code
                LEFT JOIN holding_products hp
                    ON hp.institution_code = l.institution_code
                    AND hp.product_code = l.product_code
                GROUP BY l.institution_code
                ORDER BY l.institution_code
                """
            )
        ).fetchall()
        summary.institution_rows = [
            {
                "institution_code": r.institution_code,
                "total": r.total,
                "with_nav": r.with_nav,
                "with_holding": r.with_holding,
            }
            for r in rows
        ]

        # Recent failed tasks
        failed = conn.execute(
            text(
                """
                SELECT job_name, institution_code, error_message, created_at
                FROM collection_log
                WHERE status = 'failed'
                  AND created_at > NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
        ).fetchall()
        summary.recent_failures = [
            {
                "job_name": r.job_name,
                "institution_code": r.institution_code,
                "error": (r.error_message or "")[:80],
                "created_at": r.created_at,
            }
            for r in failed
        ]

    # Failed tasks from this run (skipped is not a failure)
    summary.failed_tasks = [
        t.task_name for t in tasks if t.status == "failed"
    ]

    # Recommendations
    recommendations: list[str] = []
    if summary.product_with_nav < summary.product_total:
        missing = summary.product_total - summary.product_with_nav
        recommendations.append(
            f"{missing} 个产品仍无净值记录，建议排查对应机构采集器或补充数据源。"
        )
    if summary.product_with_holding < summary.product_total:
        missing = summary.product_total - summary.product_with_holding
        recommendations.append(
            f"{missing} 个产品仍无持仓数据，可扩展债券持仓、资产配置及银行理财持仓采集。"
        )
    if summary.market_quote_symbol_count < len(MarketQuoteCollector().all_symbols):
        missing_symbols = len(MarketQuoteCollector().all_symbols) - summary.market_quote_symbol_count
        recommendations.append(
            f"最新行情日缺少 {missing_symbols} 个品种，建议检查 market_quote 采集或补充数据源。"
        )
    if summary.failed_tasks:
        recommendations.append(
            f"本次有 {len(summary.failed_tasks)} 个任务失败，建议查看 collection_log 详情。"
        )
    if not recommendations:
        recommendations.append("本次采集整体正常，建议持续监控数据质量并定期复核。")
    summary.recommendations = recommendations

    return summary


def print_summary(summary: CollectionSummary) -> None:
    """Print the collection summary to stdout in a concise format."""
    print("\n" + "=" * 60)
    print(" FundSeeker 数据采集汇总报告")
    print("=" * 60)
    print(f"报告时间: {summary.run_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"最新产品采集日期: {summary.latest_collect_date}")
    print()

    if summary.tasks:
        print("本次执行任务:")
        for t in summary.tasks:
            if t.status == "success":
                status_icon = "✓"
            elif t.status == "skipped":
                status_icon = "⊘"
            else:
                status_icon = "✗"
            print(
                f"  [{status_icon}] {t.task_name}: {t.status}, "
                f"records={t.records_count}, "
                f"duration={t.duration_seconds:.1f}s"
            )
            if t.error_message:
                print(f"      error: {t.error_message[:80]}")
        print()

    print("数据库总体情况:")
    print(f"  产品总数: {summary.product_total}")
    print(f"  有净值产品: {summary.product_with_nav} ({_pct(summary.product_with_nav, summary.product_total)})")
    print(f"  有持仓产品: {summary.product_with_holding} ({_pct(summary.product_with_holding, summary.product_total)})")
    print(f"  净值记录数: {summary.nav_total}")
    print(f"  持仓记录数: {summary.holding_total}")
    print(f"  行情记录数: {summary.market_quote_total}")
    print(f"  最新行情日期: {summary.market_quote_latest_date}")
    print(f"  近2天有行情品种数: {summary.market_quote_symbol_count} / {len(MarketQuoteCollector().all_symbols)}")
    print()

    if getattr(summary, "institution_rows", None):
        print("各机构覆盖情况:")
        print(f"  {'机构':<12} {'产品':>8} {'有净值':>8} {'有持仓':>8}")
        for r in summary.institution_rows:
            print(
                f"  {r['institution_code']:<12} {r['total']:>8} "
                f"{r['with_nav']:>8} {r['with_holding']:>8}"
            )
        print()

    if summary.recent_failures:
        print("近 7 天失败任务:")
        for f in summary.recent_failures:
            print(f"  - {f['job_name']} ({f['institution_code']}): {f['error']}")
        print()

    print("后续建议:")
    for rec in summary.recommendations:
        print(f"  • {rec}")

    print("=" * 60)


def _pct(part: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    return f"{100.0 * part / total:.1f}%"
