"""Flask app factory + route definitions for the read-only Web UI."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, render_template, request

from fundseeker.web import queries
from fundseeker.web.queries import SimilarityRunRow


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _parse_date(value: str | None) -> date | None:
    """Parse an ISO date string (YYYY-MM-DD). Returns None on bad input."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_int(value: str | None, default: int, min_value: int = 1, max_value: int = 1000) -> int:
    try:
        n = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, n))


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(TEMPLATE_DIR),
        static_folder=str(STATIC_DIR),
    )

    register_routes(app)
    register_filters(app)
    return app


def register_filters(app: Flask) -> None:
    """Small Jinja helpers used across templates."""

    @app.template_filter("fmt_money")
    def fmt_money(value):
        if value is None:
            return "—"
        try:
            return f"{float(value):,.4f}"
        except (TypeError, ValueError):
            return str(value)

    @app.template_filter("fmt_pct")
    def fmt_pct(value):
        if value is None or value == "":
            return "—"
        try:
            return f"{float(value) * 100:,.2f}%"
        except (TypeError, ValueError):
            return str(value)

    @app.template_filter("fmt_date")
    def fmt_date(value):
        if value is None:
            return "—"
        return value.strftime("%Y-%m-%d")

    @app.template_filter("fmt_dt")
    def fmt_dt(value):
        if value is None:
            return "—"
        return value.strftime("%Y-%m-%d %H:%M:%S")

    @app.template_filter("holding_market")
    def holding_market(value):
        return queries.humanize_market(value)

    @app.template_filter("asset_class")
    def asset_class(value):
        return queries.humanize_asset_class(value)

    @app.template_filter("market_region")
    def market_region(value):
        return queries.humanize_market_region(value)

    @app.template_filter("fmt_volume")
    def fmt_volume(value, unit=None):
        """Format bigint volume to 万/亿 with a unit suffix.

        The unit is taken from the ``market_quote.volume_unit`` column:
        - ``"lot"``      (default) → "万手" / "亿手"
        - ``"share"``             → "万股" / "亿股"
        - ``"contract"``          → "万张" / "亿张"
        - ``None`` / unknown      → no suffix (numeric only)
        """
        if value is None:
            return "—"
        try:
            v = float(value)
        except (TypeError, ValueError):
            return str(value)
        suffix_map = {"lot": "手", "share": "股", "contract": "张"}
        suffix = suffix_map.get(unit, "")
        if v >= 1e8:
            return f"{v / 1e8:.2f}亿{suffix}"
        if v >= 1e4:
            return f"{v / 1e4:.2f}万{suffix}"
        return f"{v:,.0f}{suffix}"

    @app.template_filter("fmt_amount")
    def fmt_amount(value):
        """Format decimal amount to 万/亿."""
        if value is None or value == "":
            return "—"
        try:
            v = float(value)
        except (TypeError, ValueError):
            return str(value)
        if v >= 1e8:
            return f"{v / 1e8:.2f}亿"
        if v >= 1e4:
            return f"{v / 1e4:.2f}万"
        return f"{v:,.2f}"


def register_routes(app: Flask) -> None:
    # ---------------------------------------------------------------- pages
    @app.route("/")
    def search():
        institution = request.args.get("institution") or None
        product_type = request.args.get("type") or None
        risk = request.args.get("risk") or None
        keyword = request.args.get("q") or None
        status = request.args.get("status") or None
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1

        items, total = queries.list_products(
            institution=institution,
            product_type=product_type,
            risk=risk,
            keyword=keyword,
            status=status,
            page=page,
            page_size=25,
        )
        pages = max(1, (total + 24) // 25)

        return render_template(
            "search.html",
            items=items,
            total=total,
            page=page,
            pages=pages,
            institutions=queries.distinct_institutions(),
            statuses=queries.distinct_statuses(),
            product_types=queries.PRODUCT_TYPES,
            risk_levels=queries.RISK_LEVELS,
            current={
                "institution": institution or "",
                "type": product_type or "",
                "risk": risk or "",
                "status": status or "",
                "q": keyword or "",
            },
        )

    @app.route("/product/<int:product_id>")
    def product_detail(product_id: int):
        product = queries.get_product(product_id)
        if product is None:
            abort(404)
        # product_info is a snapshot table: aggregate NAV and holding reports
        # across all snapshots of the same logical product.
        nav_records = queries.list_nav_by_product_code(
            product.institution_code, product.product_code, limit=50
        )
        nav_total = queries.nav_count_by_product_code(
            product.institution_code, product.product_code
        )
        returns = queries.list_returns(product_id)
        fees = queries.list_fees(product_id)
        recent_logs = queries.recent_logs_for_institution(
            product.institution_code, limit=5
        )

        # Holdings --------------------------------------------------------
        holding_reports = queries.list_holding_reports_by_product_code(
            product.institution_code, product.product_code
        )
        selected_report_id = request.args.get("report_id", type=int)
        selected_report = None
        if selected_report_id is not None:
            for r in holding_reports:
                if r.id == selected_report_id:
                    selected_report = r
                    break
        if selected_report is None and holding_reports:
            selected_report = holding_reports[0]

        holdings: list = []
        asset_allocations: list = []
        holding_summary = None
        style_tags: list = []
        if selected_report is not None:
            holdings = queries.list_holdings(
                selected_report.id, only_top10=False
            )
            asset_allocations = queries.list_asset_allocation(selected_report.id)
            holding_summary = queries.get_holding_summary(selected_report.id)
            style_tags = queries.list_style_tags(
                product_id, selected_report.report_date
            )

        # Lookup security reference info keyed by (asset_code, market) so the
        # template can annotate individual rows without issuing more queries.
        security_info_map: dict[tuple[str, str], object] = {}
        for h in holdings:
            if h.asset_code and (h.asset_code, h.market or "UNKNOWN") not in security_info_map:
                info = queries.get_security_info(
                    h.asset_code, h.market or "UNKNOWN"
                )
                security_info_map[(h.asset_code, h.market or "UNKNOWN")] = info

        chart_labels = [r.nav_date.strftime("%Y-%m-%d") for r in reversed(nav_records)]
        chart_values = [float(r.unit_nav) for r in reversed(nav_records)]

        return render_template(
            "product.html",
            product=product,
            nav_records=nav_records,
            nav_total=nav_total,
            returns=returns,
            fees=fees,
            recent_logs=recent_logs,
            chart_labels=chart_labels,
            chart_values=chart_values,
            holding_reports=holding_reports,
            selected_report=selected_report,
            holdings=holdings,
            asset_allocations=asset_allocations,
            holding_summary=holding_summary,
            style_tags=style_tags,
            security_info_map=security_info_map,
        )

    @app.route("/holdings")
    def holdings_browse():
        asset_type = request.args.get("asset_type") or None
        market = request.args.get("market") or None
        institution = request.args.get("institution") or None
        asset_keyword = request.args.get("q") or None
        report_date = _parse_date(request.args.get("report_date"))
        only_top10 = request.args.get("top10") == "1"
        min_weight_raw = request.args.get("min_weight")
        min_weight: float | None = None
        if min_weight_raw:
            try:
                min_weight = float(min_weight_raw) / 100.0
            except ValueError:
                min_weight = None
        page = _parse_int(request.args.get("page"), default=1, min_value=1, max_value=10_000)

        rows, total = queries.search_holdings(
            asset_type=asset_type,
            market=market,
            institution=institution,
            asset_keyword=asset_keyword,
            min_weight=min_weight,
            only_top10=only_top10,
            report_date=report_date,
            page=page,
            page_size=25,
        )
        page_size = 25
        pages = max(1, (total + page_size - 1) // page_size)

        return render_template(
            "holdings.html",
            rows=rows,
            total=total,
            page=page,
            pages=pages,
            asset_types=queries.HOLDING_ASSET_TYPES,
            markets=queries.HOLDING_MARKETS,
            institutions=queries.distinct_institutions(),
            report_dates=queries.distinct_holding_report_dates(limit=12),
            current={
                "asset_type": asset_type or "",
                "market": market or "",
                "institution": institution or "",
                "q": asset_keyword or "",
                "min_weight": min_weight_raw or "",
                "top10": "1" if only_top10 else "",
                "report_date": report_date.isoformat() if report_date else "",
            },
        )

    @app.route("/dashboard")
    def dashboard():
        summary = queries.dashboard_summary()
        market = queries.market_summary()
        return render_template(
            "dashboard.html", summary=summary, market=market
        )

    # ---------------------------------------------------------------- similarity pages
    @app.route("/similarity")
    def similarity_index():
        algorithm = request.args.get("algorithm") or None
        report_date = _parse_date(request.args.get("date"))
        runs = queries.list_similarity_runs(
            algorithm=algorithm, report_date=report_date
        )
        algorithms = queries.distinct_similarity_algorithms()
        dates = queries.distinct_similarity_report_dates(limit=12)

        # Cross-run comparison context (small payload).
        compare_runs = queries.list_similarity_runs(limit=50)

        # KPI strip values.
        distinct_algos = sorted({r.algorithm for r in runs})
        latest_run = runs[0] if runs else None

        return render_template(
            "similarity_index.html",
            runs=runs,
            algorithms=algorithms,
            dates=dates,
            compare_runs=compare_runs,
            current={"algorithm": algorithm or "", "date": report_date},
            kpi={
                "run_total": len(runs),
                "algo_total": len(distinct_algos),
                "date_total": len({r.report_date for r in runs}),
                "latest_run": latest_run,
            },
        )

    @app.route("/similarity/compare")
    def similarity_compare():
        runs = queries.list_similarity_runs(limit=50)
        # Group by algorithm for multi-series scatter chart.
        by_algo: dict[str, list[SimilarityRunRow]] = {}
        for r in runs:
            by_algo.setdefault(r.algorithm, []).append(r)
        return render_template(
            "similarity_compare.html",
            runs=runs,
            by_algo=by_algo,
        )

    @app.route("/similarity/<int:cluster_run_id>")
    def similarity_run_detail(cluster_run_id: int):
        detail = queries.get_similarity_run_by_id(cluster_run_id)
        if detail is None:
            abort(404)
        all_runs = queries.list_similarity_runs(limit=50)

        # Composite NAV period change for every cluster, aligned with the
        # single-cluster detail page window (default 60 days ending today-1).
        end_date = date.today() - timedelta(days=1)
        cluster_period_changes = queries.cluster_run_period_changes(
            cluster_run_id, days=60, end_date=end_date
        )

        # Industry aggregation: collect (industry, cluster_id, weight).
        industry_rows: list[dict[str, Any]] = []
        # Enrich each cluster's top_holdings with asset_name.
        enriched_clusters = []
        for cluster in detail.clusters:
            enriched_holdings = queries.enrich_top_holdings_with_names(
                cluster.top_holdings or []
            )
            derived_label = queries.derive_cluster_label(
                cluster.top_industries or []
            )
            display_label = (
                cluster.cluster_label
                or derived_label
                or f"簇 #{cluster.cluster_id}"
            )
            enriched_clusters.append(
                {
                    "cluster_id": cluster.cluster_id,
                    "size": cluster.size,
                    "cluster_label": display_label,
                    "cluster_label_short": display_label,
                    "top_holdings": enriched_holdings,
                    "top_industries": cluster.top_industries or [],
                    "avg_hhi": cluster.avg_hhi,
                    "avg_overlap": cluster.avg_overlap,
                    "avg_overlap_raw": cluster.avg_overlap_raw,
                    "ac_share_dominance_ratio": cluster.ac_share_dominance_ratio,
                    "institution_distribution": cluster.institution_distribution,
                    "representative_products": cluster.representative_products,
                    "representative_codes": cluster.representative_codes,
                    "representative_names": cluster.representative_names,
                }
            )
            for ind in cluster.top_industries or []:
                industry_rows.append(
                    {
                        "industry": ind.get("industry", "未知行业"),
                        "weight": float(ind.get("weight") or 0.0),
                        "cluster_id": cluster.cluster_id,
                    }
                )
        industry_rows.sort(key=lambda x: x["weight"], reverse=True)

        return render_template(
            "similarity_run.html",
            detail=detail,
            clusters_view=enriched_clusters,
            all_runs=all_runs,
            industry_rows=industry_rows,
            cluster_period_changes=cluster_period_changes,
        )

    @app.route("/similarity/<int:cluster_run_id>/cluster/<int:cluster_id>")
    def similarity_cluster_detail(cluster_run_id: int, cluster_id: int):
        days = _parse_int(request.args.get("days"), default=60, min_value=10, max_value=180)
        sort = request.args.get("sort", default="distance")
        # Reference date for the market and NAV windows. Market data and
        # product NAV both lag one trading day, so the "as-of today" view
        # actually ends at `today - 1`. This is the same date both the
        # market overlay and the cluster composite NAV use as their right
        # edge, so the two series share a common time axis.
        end_date = date.today() - timedelta(days=1)
        detail = queries.get_similarity_run_by_id(cluster_run_id)
        if detail is None:
            abort(404)
        cluster = next((c for c in detail.clusters if c.cluster_id == cluster_id), None)
        if cluster is None:
            abort(404)
        # Enrich top_holdings with asset_name from holding_security_info.
        enriched_holdings = queries.enrich_top_holdings_with_names(
            cluster.top_holdings or []
        )
        # Derive a human-readable label from the cluster's top industries so
        # investors can read the investment theme straight off the title
        # (e.g. "通信 + 半导体", "白酒 + 消费"). Falls back to the stored
        # cluster_label or the sequential id when industries aren't known.
        derived_label = queries.derive_cluster_label(
            cluster.top_industries or []
        )
        display_label = (
            cluster.cluster_label
            or derived_label
            or f"簇 #{cluster.cluster_id}"
        )
        label_source = "stored" if cluster.cluster_label else (
            "industries" if derived_label else "id"
        )
        # Build a dataclass-like stand-in carrying enriched holdings for the
        # template — we re-use the existing SimilarityClusterRow by replacing
        # top_holdings via a small wrapper dict.
        cluster_view = {
            "cluster_id": cluster.cluster_id,
            "size": cluster.size,
            "cluster_label": display_label,
            "cluster_label_source": label_source,
            "top_holdings": enriched_holdings,
            "top_industries": cluster.top_industries or [],
            "avg_hhi": cluster.avg_hhi,
            "avg_overlap": cluster.avg_overlap,
            "avg_overlap_raw": cluster.avg_overlap_raw,
            "ac_share_dominance_ratio": cluster.ac_share_dominance_ratio,
            "institution_distribution": cluster.institution_distribution,
            "representative_products": cluster.representative_products,
            "representative_codes": cluster.representative_codes,
            "representative_names": cluster.representative_names,
        }
        members = queries.list_similarity_members(
            cluster_run_id=cluster_run_id,
            cluster_id=cluster_id,
            limit=200,
            sort=sort,
        )
        market_chart_data = queries.cluster_market_overlay(
            top_holdings=cluster.top_holdings or [],
            days=days,
            end_date=end_date,
        )
        breakdown = queries.cluster_market_breakdown(cluster.top_holdings or [])
        distance_histogram = queries.cluster_distance_histogram(
            [m.distance_to_center for m in members]
        )
        # Per-member NAV snapshot over the same lookback window as the chart,
        # dispersion metrics, and the composite NAV time series.
        member_value_rows = queries.cluster_member_value_snapshot(
            cluster_run_id=cluster_run_id,
            cluster_id=cluster_id,
            days=days,
            end_date=end_date,
        )
        dispersion = queries.cluster_value_dispersion(member_value_rows)
        composite_series = queries.cluster_composite_value_series(
            member_value_rows, days=days, end_date=end_date
        )
        return render_template(
            "similarity_cluster.html",
            detail=detail,
            cluster=cluster_view,
            members=members,
            market_chart_data=market_chart_data,
            market_breakdown=breakdown,
            distance_histogram=distance_histogram,
            member_value_rows=member_value_rows,
            dispersion=dispersion,
            end_date=end_date,
            window_start=end_date - timedelta(days=days),
            query_date=date.today(),
            composite_series=composite_series,
            days=days,
            sort=sort,
        )

    @app.route("/similarity/products/<int:product_id>")
    def similarity_product_view(product_id: int):
        product = queries.get_product(product_id)
        if product is None:
            abort(404)
        memberships = queries.list_product_cluster_memberships(product_id)
        return render_template(
            "similarity_product.html",
            product=product,
            memberships=memberships,
        )

    @app.route("/market")
    def market_dashboard():
        selected_date = _parse_date(request.args.get("date"))
        quotes = queries.list_market_quotes(quote_date=selected_date)
        dates = queries.distinct_market_dates(limit=30)

        # Build chart data: one dataset per symbol with close price history.
        # Align the history window with the selected (or current) date so the
        # sparklines match the table snapshot. Fetch all 30-day histories in
        # a single SQL round-trip instead of one query per symbol.
        chart_end = selected_date or date.today()
        sorted_quotes = sorted(quotes, key=lambda x: (x.market_region, x.symbol_code))
        history_by_code = queries.market_quote_history_batch(
            [q.symbol_code for q in sorted_quotes],
            days=30,
            end_date=chart_end,
        )
        chart_datasets: list[dict[str, Any]] = []
        for q in sorted_quotes:
            chart_datasets.append({
                "label": q.symbol_name,
                "code": q.symbol_code,
                "region": q.market_region,
                "data": history_by_code.get(q.symbol_code, []),
            })

        return render_template(
            "market.html",
            quotes=quotes,
            dates=dates,
            selected_date=selected_date,
            chart_datasets=chart_datasets,
            regions=queries.MARKET_REGIONS,
            asset_classes=queries.MARKET_ASSET_CLASSES,
        )

    # ---------------------------------------------------------------- api
    @app.route("/api/products")
    def api_products():
        institution = request.args.get("institution") or None
        product_type = request.args.get("type") or None
        risk = request.args.get("risk") or None
        keyword = request.args.get("q") or None
        status = request.args.get("status") or None
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1

        items, total = queries.list_products(
            institution=institution,
            product_type=product_type,
            risk=risk,
            keyword=keyword,
            status=status,
            page=page,
            page_size=25,
        )
        return jsonify(
            {
                "items": [it.to_dict() for it in items],
                "total": total,
                "page": page,
                "pages": max(1, (total + 24) // 25),
            }
        )

    @app.route("/api/products/<int:product_id>/nav")
    def api_product_nav(product_id: int):
        product = queries.get_product(product_id)
        if product is None:
            abort(404)
        nav = queries.list_nav_by_product_code(
            product.institution_code, product.product_code, limit=1000
        )
        return jsonify(
            [
                {
                    "nav_date": r.nav_date.isoformat(),
                    "unit_nav": float(r.unit_nav),
                    "cumulative_nav": (
                        float(r.cumulative_nav) if r.cumulative_nav is not None else None
                    ),
                    "daily_return": (
                        float(r.daily_return) if r.daily_return is not None else None
                    ),
                }
                for r in nav
            ]
        )

    @app.route("/api/products/<int:product_id>/holdings")
    def api_product_holdings(product_id: int):
        product = queries.get_product(product_id)
        if product is None:
            abort(404)
        report_id = request.args.get("report_id", type=int)
        if report_id is None:
            report = queries.latest_holding_report_by_product_code(
                product.institution_code, product.product_code
            )
            if report is None:
                return jsonify({"report": None, "holdings": []})
            report_id = report.id

        holdings = queries.list_holdings(report_id)
        allocation = queries.list_asset_allocation(report_id)
        summary = queries.get_holding_summary(report_id)
        return jsonify(
            {
                "report_id": report_id,
                "holdings": [
                    {
                        "asset_code": h.asset_code,
                        "asset_name": h.asset_name,
                        "asset_type": h.asset_type,
                        "sub_type": h.sub_type,
                        "market": h.market,
                        "industry_name": h.industry_name,
                        "weight": float(h.weight) if h.weight is not None else None,
                        "market_value": (
                            float(h.market_value) if h.market_value is not None else None
                        ),
                        "share_quantity": (
                            float(h.share_quantity)
                            if h.share_quantity is not None
                            else None
                        ),
                        "is_top10": h.is_top10,
                        "sort_order": h.sort_order,
                    }
                    for h in holdings
                ],
                "asset_allocation": [
                    {
                        "asset_class": a.asset_class,
                        "weight": float(a.weight) if a.weight is not None else None,
                        "market_value": (
                            float(a.market_value)
                            if a.market_value is not None
                            else None
                        ),
                    }
                    for a in allocation
                ],
                "summary": (
                    {
                        "top10_weight": (
                            float(summary.top10_weight)
                            if summary.top10_weight is not None
                            else None
                        ),
                        "stock_weight": (
                            float(summary.stock_weight)
                            if summary.stock_weight is not None
                            else None
                        ),
                        "bond_weight": (
                            float(summary.bond_weight)
                            if summary.bond_weight is not None
                            else None
                        ),
                        "cash_weight": (
                            float(summary.cash_weight)
                            if summary.cash_weight is not None
                            else None
                        ),
                        "fund_weight": (
                            float(summary.fund_weight)
                            if summary.fund_weight is not None
                            else None
                        ),
                        "derivative_weight": (
                            float(summary.derivative_weight)
                            if summary.derivative_weight is not None
                            else None
                        ),
                        "non_standard_weight": (
                            float(summary.non_standard_weight)
                            if summary.non_standard_weight is not None
                            else None
                        ),
                        "other_weight": (
                            float(summary.other_weight)
                            if summary.other_weight is not None
                            else None
                        ),
                        "concentration_score": (
                            float(summary.concentration_score)
                            if summary.concentration_score is not None
                            else None
                        ),
                        "holding_count": summary.holding_count,
                    }
                    if summary is not None
                    else None
                ),
            }
        )

    @app.route("/api/holdings")
    def api_holdings_search():
        asset_type = request.args.get("asset_type") or None
        market = request.args.get("market") or None
        institution = request.args.get("institution") or None
        asset_keyword = request.args.get("q") or None
        report_date = _parse_date(request.args.get("report_date"))
        only_top10 = request.args.get("top10") == "1"
        min_weight: float | None = None
        min_weight_raw = request.args.get("min_weight")
        if min_weight_raw:
            try:
                min_weight = float(min_weight_raw) / 100.0
            except ValueError:
                min_weight = None
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1

        rows, total = queries.search_holdings(
            asset_type=asset_type,
            market=market,
            institution=institution,
            asset_keyword=asset_keyword,
            min_weight=min_weight,
            only_top10=only_top10,
            report_date=report_date,
            page=page,
            page_size=25,
        )
        return jsonify(
            {
                "items": [r.to_dict() for r in rows],
                "total": total,
                "page": page,
                "pages": max(1, (total + 24) // 25),
            }
        )

    @app.route("/api/dashboard/summary")
    def api_dashboard_summary():
        s = queries.dashboard_summary()
        s["last_success_at"] = (
            s["last_success_at"].isoformat() if s["last_success_at"] else None
        )
        s["latest_holding_date"] = (
            s["latest_holding_date"].isoformat()
            if s.get("latest_holding_date")
            else None
        )
        s["recent_logs"] = [
            {
                "id": log.id,
                "job_name": log.job_name,
                "institution_code": log.institution_code,
                "start_time": log.start_time.isoformat() if log.start_time else None,
                "end_time": log.end_time.isoformat() if log.end_time else None,
                "status": log.status,
                "records_count": log.records_count,
                "error_message": log.error_message,
            }
            for log in s["recent_logs"]
        ]
        return jsonify(s)

    @app.route("/api/market/quotes")
    def api_market_quotes():
        selected_date = _parse_date(request.args.get("date"))
        region = request.args.get("region") or None
        quotes = queries.list_market_quotes(quote_date=selected_date, region=region)
        return jsonify({
            "date": selected_date.isoformat() if selected_date else None,
            "count": len(quotes),
            "items": [q.to_dict() for q in quotes],
        })

    # ---------------------------------------------------------------- similarity api
    @app.route("/api/similarity/runs")
    def api_similarity_runs():
        algorithm = request.args.get("algorithm") or None
        report_date = _parse_date(request.args.get("date"))
        runs = queries.list_similarity_runs(
            algorithm=algorithm, report_date=report_date
        )
        return jsonify({
            "items": [r.to_dict() for r in runs],
            "total": len(runs),
        })

    @app.route("/api/similarity/runs/<int:cluster_run_id>")
    def api_similarity_run(cluster_run_id: int):
        detail = queries.get_similarity_run_by_id(cluster_run_id)
        if detail is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify(detail.to_dict())

    @app.route("/api/similarity/runs/<int:cluster_run_id>/clusters/<int:cluster_id>")
    def api_similarity_cluster(cluster_run_id: int, cluster_id: int):
        days = _parse_int(request.args.get("days"), default=60, min_value=10, max_value=180)
        members_limit = _parse_int(
            request.args.get("members_limit"), default=200, min_value=10, max_value=2000
        )
        sort = request.args.get("sort", default="distance")
        detail = queries.get_similarity_run_by_id(cluster_run_id)
        if detail is None:
            return jsonify({"error": "run_not_found"}), 404
        cluster = next((c for c in detail.clusters if c.cluster_id == cluster_id), None)
        if cluster is None:
            return jsonify({"error": "cluster_not_found"}), 404
        members = queries.list_similarity_members(
            cluster_run_id=cluster_run_id,
            cluster_id=cluster_id,
            limit=members_limit,
            sort=sort,
        )
        return jsonify({
            "run": detail.run.to_dict(),
            "cluster": cluster.to_dict(),
            "members": [m.to_dict() for m in members],
            "market_chart": queries.cluster_market_overlay(
                top_holdings=cluster.top_holdings or [],
                days=days,
            ),
            "market_breakdown": queries.cluster_market_breakdown(
                cluster.top_holdings or []
            ),
            "distance_histogram": queries.cluster_distance_histogram(
                [m.distance_to_center for m in members]
            ),
        })

    @app.route("/api/similarity/products/<int:product_id>")
    def api_similarity_product(product_id: int):
        product = queries.get_product(product_id)
        if product is None:
            return jsonify({"error": "not_found"}), 404
        return jsonify({
            "product_id": product.id,
            "product_code": product.product_code,
            "product_name": product.product_name,
            "memberships": queries.list_product_cluster_memberships(product_id),
        })

    @app.route("/api/similarity/compare")
    def api_similarity_compare():
        runs = queries.list_similarity_runs(limit=50)
        return jsonify({"runs": [r.to_dict() for r in runs]})

    @app.route("/api/similarity/cluster-market-overlay")
    def api_similarity_cluster_market_overlay():
        cluster_run_id = request.args.get("cluster_run_id", type=int)
        cluster_id = request.args.get("cluster_id", type=int)
        days = _parse_int(request.args.get("days"), default=60, min_value=10, max_value=180)
        end_date = _parse_date(request.args.get("end_date")) or (date.today() - timedelta(days=1))
        if cluster_run_id is None or cluster_id is None:
            return jsonify({"error": "missing_params"}), 400
        detail = queries.get_similarity_run_by_id(cluster_run_id)
        if detail is None:
            return jsonify({"error": "run_not_found"}), 404
        cluster = next((c for c in detail.clusters if c.cluster_id == cluster_id), None)
        if cluster is None:
            return jsonify({"error": "cluster_not_found"}), 404
        return jsonify(
            queries.cluster_market_overlay(
                top_holdings=cluster.top_holdings or [],
                days=days,
                end_date=end_date,
            )
        )

    # ---------------------------------------------------------------- errors
    @app.errorhandler(404)
    def not_found(_e):
        return render_template("404.html"), 404
