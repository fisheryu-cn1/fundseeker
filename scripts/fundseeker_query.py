#!/usr/bin/env python3
"""Read-only retrieval CLI for FundSeeker — outputs Markdown for agents.

This script is the agent-friendly counterpart to the read-only Web UI.
It reuses the same query helpers from :mod:`fundseeker.web.queries` and
prints (or writes) a Markdown document that summarises the result.

The output is capped at 2000 lines so that the document can be safely fed
back to an LLM agent as part of its context window.

Subcommands mirror the Web UI pages:

==================  =============================  ===========================
Web UI              subcommand                      query helper
==================  =============================  ===========================
``/dashboard``      ``dashboard``                   :func:`dashboard_summary`
``/`` (search)      ``search``                      :func:`list_products`
``/product/<id>``   ``product <id>``                :func:`get_product` +
                                                     :func:`list_nav` +
                                                     :func:`list_holding_reports` +
                                                     :func:`list_holdings` +
                                                     :func:`list_asset_allocation` +
                                                     :func:`get_holding_summary` +
                                                     :func:`list_style_tags`
``/holdings``       ``holdings``                    :func:`search_holdings`
n/a                 ``security <code>``             :func:`get_security_info`
n/a                 ``filters``                     various ``distinct_*``
==================  =============================  ===========================

Examples
--------

Print overall data summary to stdout::

    PYTHONPATH=src python scripts/fundseeker_query.py dashboard

List YFD equity funds and write to a file::

    PYTHONPATH=src python scripts/fundseeker_query.py search \\
        --institution YFD --type equity \\
        --output /tmp/yfd-equity.md

Top-10 holdings of a single product (latest report)::

    PYTHONPATH=src python scripts/fundseeker_query.py product 24473 --top10

Cross-product holdings search (stock, market SZ, weight >= 3%)::

    PYTHONPATH=src python scripts/fundseeker_query.py holdings \\
        --asset-type stock --market SZ --min-weight 3

Look up a security::

    PYTHONPATH=src python scripts/fundseeker_query.py security 300750 --market SZ
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fundseeker.web import queries as q  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_LINES = 2000
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
INSTITUTION_CHOICES_HELP = "机构代码，例如 GF / ChinaAMC / YFD / HTF / SPD ..."


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_date(v: date | datetime | None) -> str:
    if v is None:
        return "—"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    return v.isoformat()


def _fmt_pct(v: Any) -> str:
    if v is None or v == "":
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{v:.2f}%"


def _fmt_money(v: Any) -> str:
    """Format a money value with 万/亿 suffix.

    Tolerates Decimal / float / int / None / strings, so it can be used
    directly on raw ORM column values without an explicit cast.
    """
    if v is None or v == "":
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    a = abs(v)
    if a >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if a >= 1e4:
        return f"{v / 1e4:.2f}万"
    if a >= 1:
        return f"{v:.2f}"
    return f"{v:.4f}"


_VOLUME_UNIT_SUFFIX = {"lot": "手", "share": "股", "contract": "张"}


def _fmt_volume(v: Any, unit: str | None = None) -> str:
    """Format a volume value with a unit suffix derived from ``unit``.

    Mirrors the Web UI ``fmt_volume`` filter so the CLI stays consistent.
    """
    if v is None or v == "":
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    suffix = _VOLUME_UNIT_SUFFIX.get(unit or "", "")
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}亿{suffix}"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.2f}万{suffix}"
    return f"{v:,.0f}{suffix}"


def _truncate(s: str | None, n: int = 60) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


class _Writer:
    """Append-only Markdown buffer that enforces the line cap."""

    def __init__(self, cap: int = MAX_LINES):
        self.lines: list[str] = []
        self.cap = cap
        self.truncated = False

    def append(self, line: str) -> None:
        if len(self.lines) >= self.cap:
            self.truncated = True
            return
        self.lines.append(line)

    def extend(self, lines: Iterable[str]) -> None:
        for ln in lines:
            self.append(ln)

    def render(self) -> str:
        if self.truncated and not self._has_truncation_note():
            # Allow the truncation note to bypass the cap.
            note = [
                "",
                f"> ⚠️ **输出已截断**，超过 {self.cap} 行上限。"
                "请缩小筛选范围（如加 `--min-weight`、`--top10`，"
                "减小 `--page-size`）。",
            ]
            self.lines.extend(note)
        return "\n".join(self.lines)

    def _has_truncation_note(self) -> bool:
        return any("输出已截断" in ln for ln in self.lines)


# ---------------------------------------------------------------------------
# Common header
# ---------------------------------------------------------------------------


def _write_header(
    w: _Writer, title: str, params: dict[str, Any] | None = None
) -> None:
    w.append(f"# {title}")
    w.append("")
    w.append(f"_生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}_")
    if params:
        # Drop empty / None values so the header stays compact.
        meaningful = {
            k: v for k, v in params.items() if v not in (None, "", [], False)
        }
        if meaningful:
            w.append("")
            w.append("## 查询参数")
            w.append("")
            for k, v in meaningful.items():
                w.append(f"- `{k}` = `{v}`")
    w.append("")


# ---------------------------------------------------------------------------
# Subcommand renderers
# ---------------------------------------------------------------------------


def render_dashboard(args: argparse.Namespace, w: _Writer) -> None:
    s = q.dashboard_summary()
    _write_header(w, "数据概览")

    w.append("## 总体")
    w.append("")
    w.append(f"- 产品总数: **{s['product_total']:,}**")
    w.append(f"- 覆盖机构: **{s['institution_total']}**")
    w.append(f"- 净值记录: **{s['nav_total']:,}**")
    if s.get("last_success_at"):
        w.append(
            f"- 最近成功: {_fmt_date(s['last_success_at'])}"
            f" ({s.get('last_success_job')})"
        )
    w.append("")

    w.append("## 持仓覆盖")
    w.append("")
    w.append(f"- 持仓报告数: **{s['report_total']:,}**")
    w.append(f"- 持仓明细行数: **{s['holding_total']:,}**")
    w.append(f"- 有持仓产品数: **{s['products_with_holding']:,}**")
    if s["product_total"]:
        pct = s["products_with_holding"] / s["product_total"]
        w.append(f"- 持仓产品占比: **{pct:.1%}**")
    if s.get("latest_holding_date"):
        w.append(f"- 最新报告期: **{s['latest_holding_date'].isoformat()}**")
        if s["latest_holding_institutions"]:
            w.append(
                f"  - 涉及机构: {', '.join(s['latest_holding_institutions'])}"
            )
    w.append("")

    type_label = dict(q.HOLDING_ASSET_TYPES)

    w.append("### 按资产类型")
    w.append("")
    w.append("| 资产类型 | 记录数 |")
    w.append("|---|---:|")
    for r in s["holding_by_type"]:
        w.append(
            f"| {type_label.get(r['asset_type'], r['asset_type'])} | "
            f"{r['count']:,} |"
        )
    w.append("")

    w.append("### 按机构")
    w.append("")
    w.append("| 机构 | 记录数 |")
    w.append("|---|---:|")
    for r in s["holding_by_institution"]:
        w.append(f"| {r['institution_code']} | {r['count']:,} |")
    w.append("")

    w.append("### 产品分布（机构 × 类型）")
    w.append("")
    w.append("| 机构 | 类型 | 数量 |")
    w.append("|---|---|---:|")
    for r in s["by_inst_type"]:
        w.append(
            f"| {r['institution_code']} | {r['product_type']} | {r['count']:,} |"
        )
    w.append("")


def render_filters(args: argparse.Namespace, w: _Writer) -> None:
    _write_header(w, "可筛选维度")

    sections = [
        ("产品类型", q.PRODUCT_TYPES, None),
        ("风险等级", [(c, c) for c in q.RISK_LEVELS], None),
        ("持仓资产类型", q.HOLDING_ASSET_TYPES, None),
        ("市场", q.HOLDING_MARKETS, None),
    ]
    for title, pairs, _ in sections:
        w.append(f"## {title}")
        w.append("")
        for code, label in pairs:
            w.append(f"- `{code}` — {label}")
        w.append("")

    insts = q.distinct_institutions()
    w.append(f"## 机构（实际数据：{len(insts)} 个）")
    w.append("")
    for i, c in enumerate(insts, 1):
        w.append(f"{i}. `{c}`")
    w.append("")

    statuses = q.distinct_statuses()
    w.append("## 产品状态")
    w.append("")
    for s in statuses:
        w.append(f"- `{s}`")
    w.append("")

    actual_types = q.distinct_holding_asset_types()
    w.append("## 持仓资产类型（实际数据中出现）")
    w.append("")
    for t in actual_types:
        w.append(f"- `{t}`")
    w.append("")

    dates = q.distinct_holding_report_dates(limit=12)
    w.append("## 持仓报告期")
    w.append("")
    for d in dates:
        w.append(f"- {d.isoformat()}")
    w.append("")


def render_search(args: argparse.Namespace, w: _Writer) -> None:
    page_size = min(max(args.page_size or DEFAULT_PAGE_SIZE, 1), MAX_PAGE_SIZE)
    items, total = q.list_products(
        institution=args.institution,
        product_type=args.product_type,
        risk=args.risk,
        keyword=args.keyword,
        status=args.status,
        page=args.page,
        page_size=page_size,
    )
    _write_header(
        w,
        "产品检索",
        {
            "institution": args.institution,
            "type": args.product_type,
            "risk": args.risk,
            "keyword": args.keyword,
            "status": args.status,
            "page": args.page,
            "page_size": page_size,
        },
    )
    w.append(f"**共 {total:,} 条**，当前第 {args.page} 页，返回 {len(items)} 条")
    w.append("")
    if not items:
        w.append("_无匹配结果。_")
        return

    type_label = dict(q.PRODUCT_TYPES)
    w.append(
        "| # | ID | 机构 | 代码 | 名称 | 类型 | 风险 | 状态 | "
        "最近净值 | 单位净值 |"
    )
    w.append("|---:|---:|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(items, 1):
        w.append(
            f"| {i} | {r.id} | {r.institution_code} | `{r.product_code}` | "
            f"{_truncate(r.product_name, 36)} | "
            f"{type_label.get(r.product_type, r.product_type)} | "
            f"{r.risk_level_standard or '—'} | "
            f"{r.status or '—'} | "
            f"{_fmt_date(r.latest_nav_date)} | "
            f"{r.latest_unit_nav or '—'} |"
        )


def render_product(args: argparse.Namespace, w: _Writer) -> None:
    p = q.get_product(args.product_id)
    if p is None:
        _write_header(w, f"产品 #{args.product_id}")
        w.append(f"_未找到 id={args.product_id} 的产品。_")
        return

    _write_header(
        w,
        f"产品详情 #{p.id}",
        {"report_id": args.report_id, "top10": args.top10,
         "asset_type": args.asset_type},
    )

    type_label = dict(q.PRODUCT_TYPES)
    w.append("## 基本信息")
    w.append("")
    w.append(f"- 名称: **{p.product_name}**")
    w.append(f"- 代码: `{p.product_code}`")
    w.append(f"- 机构: **{p.institution_code}** ({p.institution_name})")
    w.append(f"- 类型: {type_label.get(p.product_type, p.product_type)}"
             + (f" / {p.product_sub_type}" if p.product_sub_type else ""))
    w.append(f"- 风险等级: {p.risk_level_standard or '—'}"
             + (f" (原始: {p.risk_level})" if p.risk_level else ""))
    w.append(f"- 状态: {p.status or '—'}")
    if p.fund_manager:
        w.append(f"- 基金经理: {p.fund_manager}")
    if p.establish_date:
        w.append(f"- 成立日期: {p.establish_date.isoformat()}")
    if p.performance_benchmark:
        w.append(f"- 业绩基准: {_truncate(p.performance_benchmark, 120)}")
    w.append("")

    # NAV
    navs = q.list_nav(p.id, limit=args.nav_limit)
    w.append(f"## 净值（最近 {len(navs)} 条）")
    w.append("")
    w.append("| 日期 | 单位净值 | 累计净值 | 日收益率 |")
    w.append("|---|---|---|---|")
    for n in navs:
        w.append(
            f"| {n.nav_date.isoformat()} | "
            f"{_fmt_money(n.unit_nav)} | "
            f"{_fmt_money(n.cumulative_nav)} | "
            f"{_fmt_pct(n.daily_return)} |"
        )
    w.append("")

    # Holdings
    reports = q.list_holding_reports(p.id)
    if not reports:
        w.append("## 持仓")
        w.append("")
        w.append("_该产品暂无持仓报告。_")
        return

    report_id = args.report_id
    if report_id is None:
        latest = q.latest_holding_report(p.id)
        report_id = latest.id if latest else None

    selected = next((r for r in reports if r.id == report_id), reports[0])

    w.append("## 持仓报告列表")
    w.append("")
    w.append("| 报告 ID | 报告期 | 期间 | 数据源 | 持仓数 | Top10 占净值 |")
    w.append("|---:|---|---|---|---:|---:|")
    for r in reports:
        marker = " **(当前)**" if r.id == selected.id else ""
        w.append(
            f"| {r.id} | {r.report_date.isoformat()} | "
            f"{r.report_period or '—'} | `{r.data_source}` | "
            f"{r.holding_count or '—'} | {_fmt_pct(r.top10_weight)}{marker} |"
        )
    w.append("")

    summary = q.get_holding_summary(selected.id)
    if summary:
        w.append("### 汇总指标")
        w.append("")
        rows = [
            ("前十大持仓占比", summary.top10_weight),
            ("股票占比", summary.stock_weight),
            ("债券占比", summary.bond_weight),
            ("现金及存款占比", summary.cash_weight),
            ("基金占比", summary.fund_weight),
            ("衍生品占比", summary.derivative_weight),
            ("非标债权占比", summary.non_standard_weight),
            ("其他资产占比", summary.other_weight),
            ("集中度 (HHI)", summary.concentration_score),
            ("换手率估算", summary.turnover_indicator),
        ]
        w.append("| 指标 | 数值 |")
        w.append("|---|---:|")
        for label, val in rows:
            w.append(f"| {label} | {_fmt_pct(val)} |")
        w.append("")

    allocs = q.list_asset_allocation(selected.id)
    if allocs:
        w.append("### 大类资产配置")
        w.append("")
        w.append("| 类别 | 占净值 | 市值 |")
        w.append("|---|---:|---:|")
        for a in allocs:
            w.append(
                f"| {a.asset_class} | {_fmt_pct(a.weight)} | "
                f"{_fmt_money(a.market_value)} |"
            )
        w.append("")

    holdings = q.list_holdings(
        selected.id,
        asset_type=args.asset_type,
        only_top10=args.top10,
    )
    w.append(f"### 持仓明细（{len(holdings)} 条）")
    w.append("")
    if not holdings:
        w.append("_无匹配持仓。_")
    else:
        w.append(
            "| # | 资产代码 | 名称 | 类型/子类型 | 市场 | 行业 | "
            "占净值 | 市值 | 数量 | Top10 |"
        )
        w.append("|---:|---|---|---|---|---|---:|---:|---:|---|")
        for i, h in enumerate(holdings, 1):
            at = h.asset_type
            if h.sub_type:
                at += f" / {h.sub_type}"
            w.append(
                f"| {i} | `{h.asset_code or '—'}` | "
                f"{_truncate(h.asset_name, 30)} | {at} | "
                f"{h.market or '—'} | {_truncate(h.industry_name, 18)} | "
                f"{_fmt_pct(h.weight)} | {_fmt_money(h.market_value)} | "
                f"{_fmt_money(h.share_quantity)} | "
                f"{'是' if h.is_top10 else '—'} |"
            )
    w.append("")

    tags = q.list_style_tags(p.id, selected.report_date)
    if tags:
        w.append("### 持仓风格标签")
        w.append("")
        by_dim: dict[str, list[Any]] = {}
        for t in tags:
            by_dim.setdefault(t.dimension, []).append(t)
        for dim, lst in by_dim.items():
            w.append(f"- **{dim}**: " + ", ".join(t.tag for t in lst))
        w.append("")


def render_holdings(args: argparse.Namespace, w: _Writer) -> None:
    page_size = min(max(args.page_size or DEFAULT_PAGE_SIZE, 1), MAX_PAGE_SIZE)
    # The DB stores weights as decimal fractions (0.07 = 7%). Convert the
    # user's percentage input back to a fraction so the WHERE clause matches.
    min_weight = (
        args.min_weight / 100.0 if args.min_weight is not None else None
    )
    rows, total = q.search_holdings(
        asset_type=args.asset_type,
        market=args.market,
        institution=args.institution,
        asset_keyword=args.keyword,
        min_weight=min_weight,
        only_top10=args.top10,
        report_date=args.report_date,
        page=args.page,
        page_size=page_size,
    )
    _write_header(
        w,
        "持仓检索",
        {
            "asset_type": args.asset_type,
            "market": args.market,
            "institution": args.institution,
            "keyword": args.keyword,
            "min_weight_%": args.min_weight,
            "top10": args.top10,
            "report_date": args.report_date,
            "page": args.page,
            "page_size": page_size,
        },
    )
    w.append(f"**共 {total:,} 条**，当前第 {args.page} 页，返回 {len(rows)} 条")
    w.append("")
    if not rows:
        w.append("_无匹配持仓。_")
        return

    type_label = dict(q.HOLDING_ASSET_TYPES)
    market_label = dict(q.HOLDING_MARKETS)
    w.append(
        "| # | 报告期 | 期间 | 机构 | 产品 | 代码 | 名称 | 类型 | 市场 | "
        "行业 | 占净值 | 市值 | Top10 |"
    )
    w.append("|---:|---|---|---|---|---|---|---|---|---|---:|---:|---|")
    for i, r in enumerate(rows, 1):
        w.append(
            f"| {i} | {r.report_date.isoformat()} | {r.report_period or '—'} | "
            f"{r.institution_code} | {_truncate(r.product_name, 22)} | "
            f"`{r.asset_code or '—'}` | {_truncate(r.asset_name, 22)} | "
            f"{type_label.get(r.asset_type, r.asset_type)} | "
            f"{market_label.get(r.market, r.market or '—')} | "
            f"{_truncate(r.industry_name, 12)} | "
            f"{_fmt_pct(r.weight)} | {_fmt_money(r.market_value)} | "
            f"{'是' if r.is_top10 else '—'} |"
        )


def render_security(args: argparse.Namespace, w: _Writer) -> None:
    info = q.get_security_info(args.code, market=args.market)
    _write_header(w, f"标的查询 {args.code}", {"market": args.market})
    if info is None:
        w.append(
            f"_未找到 code={args.code}, market={args.market} 的标的。_"
        )
        return
    w.append(f"- 资产代码: `{info.asset_code}`")
    w.append(f"- 资产名称: **{info.asset_name}**")
    w.append(f"- 市场: {info.market or '—'}")
    w.append(f"- 资产类型: {info.asset_type or '—'}")
    w.append(f"- 行业: {info.industry_name or '—'}")
    if info.listing_date:
        w.append(f"- 上市日期: {info.listing_date.isoformat()}")
    w.append("")


def render_market(args: argparse.Namespace, w: _Writer) -> None:
    quote_date = _parse_iso_date(args.date) if args.date else None
    quotes = q.list_market_quotes(quote_date=quote_date, region=args.region)
    _write_header(
        w,
        "市场行情",
        {"date": args.date, "region": args.region},
    )
    w.append(f"**共 {len(quotes)} 个品种**")
    if quote_date:
        w.append(f"交易日: {quote_date.isoformat()}")
    else:
        w.append("（各品种取各自最新交易日）")
    w.append("")
    if not quotes:
        w.append("_暂无市场行情数据。_")
        return

    region_label = dict(q.MARKET_REGIONS)
    region_order = ["domestic", "us", "hk", "commodity"]
    by_region: dict[str, list] = {}
    for r in quotes:
        by_region.setdefault(r.market_region, []).append(r)

    for region in region_order:
        if region not in by_region:
            continue
        w.append(f"## {region_label.get(region, region)}")
        w.append("")
        w.append(
            "| 代码 | 名称 | 日期 | 开盘 | 最高 | 最低 | "
            "收盘 | 昨收 | 涨跌额 | 涨跌幅 | 成交量 | 单位 | 成交额 |"
        )
        w.append(
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|"
        )
        for r in by_region[region]:
            w.append(
                f"| `{r.symbol_code}` | {r.symbol_name} | "
                f"{r.quote_date.isoformat()} | "
                f"{_fmt_money(r.open_price)} | {_fmt_money(r.high_price)} | "
                f"{_fmt_money(r.low_price)} | {_fmt_money(r.close_price)} | "
                f"{_fmt_money(r.prev_close)} | "
                f"{_fmt_money(r.change_amount)} | "
                f"{_fmt_pct(r.change_pct)} | "
                f"{_fmt_volume(r.volume, r.volume_unit)} | "
                f"{r.volume_unit or '—'} | "
                f"{_fmt_money(r.amount)} |"
            )
        w.append("")


# ---------------------------------------------------------------------------
# Similarity renderers
# ---------------------------------------------------------------------------


def render_similarity_runs(args: argparse.Namespace, w: _Writer) -> None:
    report_date = _parse_iso_date(args.date) if args.date else None
    runs = q.list_similarity_runs(
        algorithm=args.algorithm, report_date=report_date
    )
    _write_header(
        w,
        "组合相似度运行列表",
        {"algorithm": args.algorithm, "date": args.date},
    )
    if not runs:
        w.append("_暂无聚类运行结果。可通过 `PYTHONPATH=src python scripts/fundseeker_similarity.py cluster ...` 生成。_")
        return

    w.append("## 概览")
    w.append(f"- 运行次数: **{len(runs)}**")
    w.append(f"- 涉及算法: **{len({r.algorithm for r in runs})}** ("
             + ", ".join(sorted({r.algorithm for r in runs})) + ")")
    w.append(f"- 最新报告期: **{runs[0].report_date.isoformat()}**")
    w.append("")

    w.append("## 详情")
    w.append(
        "| # | 报告期 | 算法 | k | 产品类型 | 产品数 | 特征维度 | "
        "Silhouette | Inertia | 创建时间 |"
    )
    w.append(
        "|---:|---|---|---:|---|---:|---:|---:|---:|---|"
    )
    for r in runs:
        w.append(
            f"| {r.cluster_run_id} | {r.report_date.isoformat()} | "
            f"`{r.algorithm}` | {r.k} | {r.product_type_filter or '全部'} | "
            f"{r.n_products or '—'} | {r.n_features or '—'} | "
            f"{_fmt_money(r.silhouette)} | "
            f"{_fmt_money(r.inertia)} | "
            f"{r.created_at.strftime('%Y-%m-%d %H:%M')} |"
        )
    w.append("")


def render_similarity_run(args: argparse.Namespace, w: _Writer) -> None:
    days = args.days or 60
    detail = q.get_similarity_run_by_id(args.run_id)
    if detail is None:
        w.append(f"**未找到运行 #{args.run_id}**")
        return
    run = detail.run
    _write_header(
        w,
        f"相似度运行 #{run.cluster_run_id}",
        {"cluster_id": args.cluster_id, "days": days},
    )
    w.append("## 运行元数据")
    w.append(f"- 报告期: {run.report_date.isoformat()}")
    w.append(f"- 算法: `{run.algorithm}`")
    w.append(f"- k: **{run.k}**")
    w.append(f"- 产品数: {run.n_products or '—'}")
    w.append(f"- 特征维度: {run.n_features or '—'}")
    w.append(f"- Silhouette: `{_fmt_money(run.silhouette)}`")
    w.append(f"- Inertia: `{_fmt_money(run.inertia)}`")
    w.append(f"- 产品类型过滤: {run.product_type_filter or '全部'}")
    w.append(f"- 创建于: {run.created_at.strftime('%Y-%m-%d %H:%M')}")
    w.append("")

    w.append(f"## 簇概览 ({len(detail.clusters)} 个簇 · 共 {len(detail.members)} 个产品)")
    w.append("")
    w.append(
        "| 簇 | 规模 | Top 行业 | Top 持仓 | 平均 HHI | 平均 Overlap | "
        "AC 份额合并 |"
    )
    w.append("|---:|---:|---|---|---:|---:|---:|")
    for c in detail.clusters:
        industries = ", ".join(
            f"{i['industry']}({_fmt_money(i['weight'])})"
            for i in (c.top_industries or [])[:3]
        ) or "—"
        holdings = ", ".join(
            f"`{h['asset_code']}`" for h in (c.top_holdings or [])[:3]
        ) or "—"
        ac = (
            f"{_fmt_money(c.ac_share_dominance_ratio)}"
            if c.ac_share_dominance_ratio and c.ac_share_dominance_ratio > 0
            else "—"
        )
        w.append(
            f"| **{c.cluster_id}** | {c.size} | {industries} | {holdings} | "
            f"{_fmt_money(c.avg_hhi)} | "
            f"{_fmt_money(c.avg_overlap)} / {_fmt_money(c.avg_overlap_raw)} | "
            f"{ac} |"
        )
    w.append("")

    if args.cluster_id is None:
        return
    cluster = next((c for c in detail.clusters if c.cluster_id == args.cluster_id), None)
    if cluster is None:
        w.append(f"**未找到簇 #{args.cluster_id}**")
        return
    members = [
        m for m in detail.members if m.cluster_id == args.cluster_id
    ]
    members.sort(
        key=lambda m: m.distance_to_center if m.distance_to_center is not None else 1e18
    )
    if args.members_limit:
        members = members[: args.members_limit]

    w.append(f"## 簇 #{cluster.cluster_id} 详情")
    w.append(f"- 规模: **{cluster.size}**")
    w.append(
        f"- Top 行业: "
        + ", ".join(
            f"{i['industry']}({_fmt_money(i['weight'])})"
            for i in (cluster.top_industries or [])
        )
    )
    w.append(
        f"- Top 持仓: "
        + ", ".join(
            f"`{h['asset_code']}`({_fmt_money(h['weight'])})"
            for h in (cluster.top_holdings or [])
        )
    )
    w.append(f"- 平均 HHI: `{_fmt_money(cluster.avg_hhi)}`")
    w.append(
        f"- 平均 Overlap (归一化 / 原始权重): "
        f"`{_fmt_money(cluster.avg_overlap)}` / `{_fmt_money(cluster.avg_overlap_raw)}`"
    )
    if cluster.institution_distribution:
        inst = ", ".join(
            f"{k}({v})" for k, v in cluster.institution_distribution.items()
        )
        w.append(f"- 机构分布: {inst}")
    w.append("")

    # Members table.
    w.append(f"### 成员 (按到质心距离排序, 展示 {len(members)} / {cluster.size})")
    w.append("")
    w.append("| # | 机构 | 代码 | 名称 | 类型 | 距离 |")
    w.append("|---:|---|---|---|---|---:|")
    for i, m in enumerate(members, 1):
        w.append(
            f"| {i} | {m.institution_code} | `{m.product_code}` | "
            f"{m.product_name} | {m.product_type} | "
            f"{_fmt_money(m.distance_to_center)} |"
        )
    w.append("")

    # Market overlay summary.
    overlay = q.cluster_market_overlay(
        top_holdings=cluster.top_holdings or [], days=days
    )
    breakdown = q.cluster_market_breakdown(cluster.top_holdings or [])
    w.append(f"### 市场对比指数 ({days} 天)")
    w.append("")
    if breakdown:
        w.append(
            "- 持仓分布: "
            + ", ".join(f"{b['label']}({_fmt_money(b['weight'])})" for b in breakdown)
        )
    w.append(
        "- 对比指数: "
        + ", ".join(f"`{d['code']}` ({d['label']})" for d in overlay)
    )
    w.append(
        "  - 各指数走势请参考 `/market` 页; 此处仅展示所选指数列表。"
    )
    w.append("")


def render_similarity_compare(args: argparse.Namespace, w: _Writer) -> None:
    runs = q.list_similarity_runs(limit=50)
    _write_header(w, "跨聚类运行对比")
    if not runs:
        w.append("_暂无聚类运行。_")
        return

    w.append("## 概览")
    w.append(f"- 总运行数: **{len(runs)}**")
    w.append(f"- 涉及算法: **{len({r.algorithm for r in runs})}**")
    sil_vals = [r.silhouette for r in runs if r.silhouette is not None]
    n_vals = [r.n_products for r in runs if r.n_products is not None]
    if sil_vals:
        w.append(f"- 最高 Silhouette: **`{max(sil_vals):.4f}`**")
    if n_vals:
        w.append(f"- 最大产品规模: **{max(n_vals)}**")
    w.append("")

    # Silhouette comparison as ASCII bar chart.
    if sil_vals:
        w.append("## Silhouette 对比 (ASCII)")
        max_sil = max(sil_vals)
        bar_width = 40
        for r in runs:
            if r.silhouette is None:
                continue
            bar_len = max(1, int(r.silhouette / max_sil * bar_width))
            bar = "█" * bar_len
            w.append(
                f"- `{r.algorithm:>20s}` k={r.k} "
                f"{r.silhouette:+.4f} `{bar}`"
            )
        w.append("")

    w.append("## 全部运行")
    w.append(
        "| # | 报告期 | 算法 | k | 产品数 | 特征维度 | "
        "Silhouette | Inertia | 创建时间 |"
    )
    w.append("|---:|---|---|---:|---:|---:|---:|---:|---|")
    for r in runs:
        w.append(
            f"| {r.cluster_run_id} | {r.report_date.isoformat()} | "
            f"`{r.algorithm}` | {r.k} | "
            f"{r.n_products or '—'} | {r.n_features or '—'} | "
            f"{_fmt_money(r.silhouette)} | "
            f"{_fmt_money(r.inertia)} | "
            f"{r.created_at.strftime('%Y-%m-%d %H:%M')} |"
        )
    w.append("")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _product_type_choices() -> list[str]:
    return [c for c, _ in q.PRODUCT_TYPES]


def _holding_asset_type_choices() -> list[str]:
    return [c for c, _ in q.HOLDING_ASSET_TYPES]


def _holding_market_choices() -> list[str]:
    return [c for c, _ in q.HOLDING_MARKETS]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fundseeker_query",
        description=(
            "Read-only retrieval CLI for FundSeeker. Wraps the Web UI "
            "queries and writes Markdown output (capped at "
            f"{MAX_LINES} lines) suitable for agent consumption."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write Markdown output to this path instead of stdout.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-o",
        "--output",
        help="Write Markdown output to this path instead of stdout.",
    )

    sub.add_parser(
        "dashboard",
        parents=[common],
        help="Print the overall data summary.",
    )

    sub.add_parser(
        "filters",
        parents=[common],
        help="List all valid filter values (institutions, types, markets…).",
    )

    sp = sub.add_parser(
        "search", parents=[common], help="Search products by various filters."
    )
    sp.add_argument("--institution", help=INSTITUTION_CHOICES_HELP)
    sp.add_argument(
        "--type",
        dest="product_type",
        choices=_product_type_choices(),
        help="Product type.",
    )
    sp.add_argument(
        "--risk",
        choices=q.RISK_LEVELS,
        help="Unified risk level L1–L5.",
    )
    sp.add_argument("--keyword", "-q", help="Match product_code or product_name.")
    sp.add_argument("--status", help="Product status (e.g. active).")
    sp.add_argument("--page", type=int, default=1)
    sp.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)

    sp = sub.add_parser(
        "product",
        parents=[common],
        help="Show one product's NAV, holdings and style tags.",
    )
    sp.add_argument("product_id", type=int, help="Product primary-key id.")
    sp.add_argument(
        "--report-id", type=int, help="Show a specific holding report id "
        "(default: latest)."
    )
    sp.add_argument(
        "--asset-type",
        choices=_holding_asset_type_choices(),
        help="Only show holdings of this asset type.",
    )
    sp.add_argument(
        "--top10", action="store_true", help="Only show top-10 holdings."
    )
    sp.add_argument(
        "--nav-limit",
        type=int,
        default=50,
        help="Number of recent NAV rows to print (default 50).",
    )

    sp = sub.add_parser(
        "holdings",
        parents=[common],
        help="Cross-product holdings browse (mirrors /holdings).",
    )
    sp.add_argument(
        "--asset-type",
        choices=_holding_asset_type_choices(),
        help="Asset type filter.",
    )
    sp.add_argument(
        "--market", choices=_holding_market_choices(), help="Market filter."
    )
    sp.add_argument("--institution", help=INSTITUTION_CHOICES_HELP)
    sp.add_argument(
        "--keyword", "-q", help="Match asset_code / asset_name / industry."
    )
    sp.add_argument(
        "--min-weight",
        type=float,
        help=(
            "Minimum weight as percentage of NAV (e.g. 1.5 means 1.5%%). "
            "Internally converted to the decimal fraction used in the DB "
            "(1.5%% → 0.015)."
        ),
    )
    sp.add_argument(
        "--top10", action="store_true", help="Only top-10 holdings."
    )
    sp.add_argument(
        "--report-date",
        help="Filter to a specific report_date (YYYY-MM-DD).",
    )
    sp.add_argument("--page", type=int, default=1)
    sp.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)

    sp = sub.add_parser(
        "security",
        parents=[common],
        help="Look up a security reference row by code.",
    )
    sp.add_argument("code", help="Asset code, e.g. 300750.")
    sp.add_argument("--market", help="Market code, e.g. SH / SZ.")

    sp = sub.add_parser(
        "market",
        parents=[common],
        help="List latest market quotes (indices + commodities).",
    )
    sp.add_argument(
        "--date",
        help="Quote date YYYY-MM-DD (default: each symbol's latest).",
    )
    sp.add_argument(
        "--region",
        choices=_market_region_choices(),
        help="Filter by market region.",
    )

    sp = sub.add_parser(
        "similarity-runs",
        parents=[common],
        help="List persisted similarity cluster runs.",
    )
    sp.add_argument(
        "--algorithm",
        help="Filter by algorithm identifier (e.g. kmeans-asset).",
    )
    sp.add_argument(
        "--date",
        help="Filter to a specific report_date (YYYY-MM-DD).",
    )

    sp = sub.add_parser(
        "similarity-run",
        parents=[common],
        help="Show one similarity cluster run and its clusters.",
    )
    sp.add_argument("run_id", type=int, help="Cluster run primary-key id.")
    sp.add_argument(
        "--cluster", dest="cluster_id", type=int, default=None,
        help="Show details (members + market overlay) for a specific cluster id.",
    )
    sp.add_argument(
        "--days", type=int, default=60,
        help="Number of days for market overlay history (default 60).",
    )
    sp.add_argument(
        "--members-limit", type=int, default=50,
        help="Max number of members to show per cluster (default 50).",
    )

    sp = sub.add_parser(
        "similarity-compare",
        parents=[common],
        help="Cross-run comparison of persisted similarity runs.",
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _market_region_choices() -> list[str]:
    return [c for c, _ in q.MARKET_REGIONS]


DISPATCH = {
    "dashboard": render_dashboard,
    "filters": render_filters,
    "search": render_search,
    "product": render_product,
    "holdings": render_holdings,
    "security": render_security,
    "market": render_market,
    "similarity-runs": render_similarity_runs,
    "similarity-run": render_similarity_run,
    "similarity-compare": render_similarity_compare,
}


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Pre-coerce report_date to a date object for queries that need it.
    if hasattr(args, "report_date") and isinstance(args.report_date, str):
        try:
            args.report_date = _parse_iso_date(args.report_date)
        except ValueError:
            print(
                f"Invalid --report-date: {args.report_date!r}, "
                "expected YYYY-MM-DD.",
                file=sys.stderr,
            )
            return 2

    w = _Writer()
    renderer = DISPATCH[args.command]
    try:
        renderer(args, w)
    except Exception as exc:  # pragma: no cover — defensive
        w.append("")
        w.append(f"**错误**: `{type(exc).__name__}: {exc}`")

    md = w.render()
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md + "\n", encoding="utf-8")
        line_count = len(md.splitlines())
        print(
            f"Wrote {line_count} lines to {out_path}", file=sys.stderr
        )
        if w.truncated:
            print(
                f"WARNING: Output truncated to {MAX_LINES} lines.",
                file=sys.stderr,
            )
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())