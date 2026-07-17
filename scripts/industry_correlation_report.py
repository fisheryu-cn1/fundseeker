#!/usr/bin/env python3
"""Generate a standalone HTML report for industry sector correlation analysis.

The report uses stock quotes in `market_quote` and industry mapping in
`holding_security_info` to build equal-weighted industry return series, then
computes pairwise correlations over a trailing window.

Output: reports/industry_correlation_report.html
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from fundseeker.models.database import get_session_maker
from fundseeker.models.tables import HoldingSecurityInfo, MarketQuote


REPORT_DIR = project_root / "reports"
MIN_STOCKS_PER_INDUSTRY = 8
MIN_TRADING_DAYS = 30
TOP_N = 15  # number of industries to highlight
WINDOW_DAYS = 60


def load_data() -> pd.DataFrame:
    """Load stock close prices joined with industry mapping."""
    Session = get_session_maker()
    with Session() as session:
        # Latest available quote date for stocks.
        max_date = session.execute(
            select(MarketQuote.quote_date)
            .where(MarketQuote.asset_class == "stock")
            .order_by(MarketQuote.quote_date.desc())
            .limit(1)
        ).scalar_one()

        start_date = max_date - timedelta(days=WINDOW_DAYS)

        # Load stock quotes and industry mapping separately, then merge in
        # Python. market_quote.symbol_code includes exchange prefix (e.g.
        # SH600000) while holding_security_info.asset_code is the 6-digit code.
        mq_stmt = (
            select(
                MarketQuote.symbol_code,
                MarketQuote.symbol_name,
                MarketQuote.quote_date,
                MarketQuote.close_price,
            )
            .where(
                MarketQuote.asset_class == "stock",
                MarketQuote.quote_date >= start_date,
                MarketQuote.quote_date <= max_date,
                MarketQuote.close_price.isnot(None),
            )
        )
        mq_rows = session.execute(mq_stmt).all()

        hs_stmt = select(
            HoldingSecurityInfo.asset_code,
            HoldingSecurityInfo.industry_name,
        ).where(HoldingSecurityInfo.industry_name.isnot(None))
        hs_rows = session.execute(hs_stmt).all()

    # Build mapping: 6-digit code -> industry.
    industry_map = {str(code).strip(): ind for code, ind in hs_rows if ind}

    rows = []
    for symbol_code, symbol_name, quote_date, close in mq_rows:
        code = str(symbol_code)
        # Strip exchange prefix (SH/SZ/BJ) to get 6-digit asset code.
        if len(code) >= 6 and code[:2] in ("SH", "SZ", "BJ"):
            asset_code = code[2:]
        else:
            asset_code = code
        industry = industry_map.get(asset_code)
        rows.append((symbol_code, symbol_name, quote_date, close, industry))

    df = pd.DataFrame(
        rows,
        columns=["symbol_code", "symbol_name", "quote_date", "close", "industry"],
    )
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])
    return df, max_date, start_date


def build_industry_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Build equal-weighted daily return series for each industry."""
    # Require industry mapping.
    df = df.dropna(subset=["industry"])
    df = df[df["industry"].str.strip() != ""]

    # Pivot to (date x symbol) close prices.
    price_pivot = df.pivot_table(
        index="quote_date",
        columns="symbol_code",
        values="close",
        aggfunc="last",
    )

    # Daily returns per stock.
    returns = price_pivot.pct_change().dropna(how="all")

    # Map symbol -> industry (use the most frequent mapping per symbol).
    symbol_industry = (
        df.groupby("symbol_code")["industry"]
        .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else s.iloc[0])
    )

    # Keep industries with enough stocks.
    industry_counts = symbol_industry.value_counts()
    valid_industries = industry_counts[industry_counts >= MIN_STOCKS_PER_INDUSTRY].index
    symbol_industry = symbol_industry[symbol_industry.isin(valid_industries)]

    # Aggregate equal-weighted industry returns.
    industry_returns = pd.DataFrame(
        index=returns.index,
        columns=sorted(valid_industries),
        dtype=float,
    )
    for industry in valid_industries:
        symbols = symbol_industry[symbol_industry == industry].index
        cols = [s for s in symbols if s in returns.columns]
        if cols:
            industry_returns[industry] = returns[cols].mean(axis=1, skipna=True)

    # Drop industries with too few valid return observations.
    industry_returns = industry_returns.dropna(axis=1, thresh=MIN_TRADING_DAYS)
    industry_returns = industry_returns.dropna(axis=0, how="all")
    return industry_returns


def shorten_industry(name: str) -> str:
    """Drop common suffixes to make chart labels cleaner."""
    name = name.strip()
    # Special-case readability for a few sectors.
    if name in ("银行Ⅱ", "银行"):
        return "银行业"
    suffixes = ("Ⅱ", "III", "II", "I")
    for suf in suffixes:
        if name.endswith(suf):
            return name[: -len(suf)].rstrip() or name
    return name


def compute_correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    """Pairwise Pearson correlation of industry returns."""
    return returns.corr(method="pearson", min_periods=20)


def hierarchical_order(corr: pd.DataFrame) -> list[str]:
    """Return industry labels ordered by greedy seriation.

    Places highly correlated industries next to each other so patterns are
    easier to see in the heatmap. No external clustering library required.
    """
    if len(corr) <= 2:
        return list(corr.index)
    remaining = set(corr.index)
    # Start with the industry most correlated with the rest of the market.
    start = corr.sum(axis=1).idxmax()
    order = [start]
    remaining.remove(start)
    while remaining:
        last = order[-1]
        # Pick the remaining industry most correlated with the last placed one.
        next_ind = max(remaining, key=lambda x: corr.loc[last, x])
        order.append(next_ind)
        remaining.remove(next_ind)
    return order


def top_pairs(corr: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Most positively and negatively correlated industry pairs."""
    # Upper triangle, exclude diagonal.
    triu = np.triu(np.ones(corr.shape), k=1).astype(bool)
    pairs = []
    for i, j in zip(*np.where(triu)):
        pairs.append(
            {
                "industry_a": corr.index[i],
                "industry_b": corr.columns[j],
                "corr": float(corr.iloc[i, j]),
            }
        )
    pairs_df = pd.DataFrame(pairs).dropna()
    pairs_df["abs_corr"] = pairs_df["corr"].abs()
    positive = pairs_df[pairs_df["corr"] > 0].nlargest(n, "corr")
    negative = pairs_df[pairs_df["corr"] < 0].nsmallest(n, "corr")
    strongest = pairs_df.nlargest(n, "abs_corr")
    return positive, negative, strongest


def banking_correlations(corr: pd.DataFrame, n: int = 10):
    """Return correlations between the banking sector and all other industries.

    Returns a tuple (positive_top, negative_top, full) or None if banking is not
    present. All dataframes are sorted by correlation strength.
    """
    bank_names = [name for name in corr.index if name in ("银行Ⅱ", "银行")]
    if not bank_names:
        return None
    bank_name = bank_names[0]
    series = corr.loc[bank_name].drop(labels=[bank_name])
    df = pd.DataFrame({"industry": series.index, "corr": series.values})
    df = df.dropna()
    positive = df[df["corr"] > 0].nlargest(n, "corr")
    negative = df[df["corr"] < 0].nsmallest(n, "corr")
    full = df.sort_values("corr", ascending=False)
    return positive, negative, full


def generate_html(
    corr: pd.DataFrame,
    returns: pd.DataFrame,
    max_date: date,
    start_date: date,
    output_path: Path,
) -> None:
    """Write a standalone interactive HTML report."""
    ordered = hierarchical_order(corr)
    corr_ordered = corr.loc[ordered, ordered]
    short_labels = [shorten_industry(x) for x in corr_ordered.index]

    # Heatmap data.
    z = corr_ordered.values.tolist()

    # Cumulative return series per industry (rebased to 100).
    cum_returns = (1 + returns).cumprod()
    cum_returns = cum_returns / cum_returns.iloc[0] * 100
    cum_returns = cum_returns.loc[:, corr_ordered.index]
    cum_series = {
        shorten_industry(name): {
            "x": [d.isoformat() for d in cum_returns.index],
            "y": cum_returns[name].round(3).tolist(),
        }
        for name in cum_returns.columns
    }

    positive, negative, strongest = top_pairs(corr, n=10)
    bank_corr = banking_correlations(corr)

    summary = {
        "n_industries": int(len(corr)),
        "date_range": f"{start_date.isoformat()} ~ {max_date.isoformat()}",
        "n_trading_days": int(len(returns)),
        "mean_abs_corr": float(corr.abs().mean().mean()),
        "max_corr": float(corr.values[np.triu_indices_from(corr.values, k=1)].max()),
        "min_corr": float(corr.values[np.triu_indices_from(corr.values, k=1)].min()),
    }

    template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>行业板块相关性分析报告</title>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f7fa; margin: 0; padding: 0; min-width: fit-content; }
    .container { margin: 0 auto; padding: 24px; }
    h1 { font-size: 1.6rem; margin-bottom: 0.5rem; }
    .subtitle { color: #666; margin-bottom: 1.5rem; }
    .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }
    .card { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
    .card .label { font-size: 0.85rem; color: #888; margin-bottom: 6px; }
    .card .value { font-size: 1.3rem; font-weight: 600; }
    .section { background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
    .section h2 { font-size: 1.15rem; margin-top: 0; margin-bottom: 16px; }
    .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    @media (max-width: 768px) { .two-col { grid-template-columns: 1fr; } }
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #eee; }
    th { background: #f8f9fa; font-weight: 600; }
    .corr-pos { color: #dc3545; font-weight: 600; }
    .corr-neg { color: #198754; font-weight: 600; }
    .footnote { color: #888; font-size: 0.85rem; margin-top: 8px; }
  </style>
</head>
<body>
  <div class="container">
    <h1>行业板块相关性分析报告</h1>
    <div class="subtitle">基于 A 股个股日行情与持仓证券行业映射 · {{date_range}}</div>

    <div class="summary">
      <div class="card">
        <div class="label">覆盖行业数</div>
        <div class="value">{{n_industries}}</div>
      </div>
      <div class="card">
        <div class="label">交易日数</div>
        <div class="value">{{n_trading_days}}</div>
      </div>
      <div class="card">
        <div class="label">平均绝对相关度</div>
        <div class="value">{{mean_abs_corr}}</div>
      </div>
      <div class="card">
        <div class="label">最高相关</div>
        <div class="value">{{max_corr}}</div>
      </div>
      <div class="card">
        <div class="label">最低相关</div>
        <div class="value">{{min_corr}}</div>
      </div>
    </div>

    <div class="section">
      <h2>行业收益走势（标准化为 100）</h2>
      <div id="returns-chart" style="height: 520px;"></div>
      <div class="footnote">每条线为等权合成的行业日收益累计曲线；起点统一归一化为 100。</div>
    </div>

    <div class="section">
      <h2>行业相关性热力图</h2>
      <div id="heatmap" style="height: 800px;"></div>
      <div class="footnote">颜色越红表示正相关越强，越绿表示负相关越强；行列已按贪心排序（高相关板块相邻）重新排列。</div>
    </div>

    <div class="two-col">
      <div class="section">
        <h2>正相关最高的行业对</h2>
        <table>
          <thead><tr><th>行业 A</th><th>行业 B</th><th>相关系数</th></tr></thead>
          <tbody>{{positive_rows}}</tbody>
        </table>
      </div>
      <div class="section">
        <h2>负相关最强的行业对</h2>
        <table>
          <thead><tr><th>行业 A</th><th>行业 B</th><th>相关系数</th></tr></thead>
          <tbody>{{negative_rows}}</tbody>
        </table>
      </div>
    </div>

    <div class="section">
      <h2>相关性绝对值最高的行业对</h2>
      <table>
        <thead><tr><th>行业 A</th><th>行业 B</th><th>相关系数</th></tr></thead>
        <tbody>{{strongest_rows}}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>银行业与各行业相关性</h2>
      <p class="footnote">银行业（<code>银行Ⅱ</code>）与各行业板块日收益率的 Pearson 相关系数。该表与上方「正相关最高 / 负相关最强」行业对完全对应，只是按银行业视角重新组织。</p>
      <div class="two-col">
        <div>
          <h3>正相关最强</h3>
          <table>
            <thead><tr><th>行业</th><th>相关系数</th></tr></thead>
            <tbody>{{banking_positive_rows}}</tbody>
          </table>
        </div>
        <div>
          <h3>负相关最强</h3>
          <table>
            <thead><tr><th>行业</th><th>相关系数</th></tr></thead>
            <tbody>{{banking_negative_rows}}</tbody>
          </table>
        </div>
      </div>
      <details style="margin-top: 16px;">
        <summary>查看完整排序</summary>
        <table>
          <thead><tr><th>行业</th><th>相关系数</th></tr></thead>
          <tbody>{{banking_full_rows}}</tbody>
        </table>
      </details>
      <div class="footnote">正值表示与银行业同向波动，负值表示反向波动；可用于判断市场风格（成长/价值、大盘/小盘）的分化。</div>
    </div>

    <div class="section">
      <h2>方法说明</h2>
      <p class="footnote">
        1. 数据源：<code>market_quote</code> 中 asset_class=stock 的 A 股日收盘价，<code>holding_security_info</code> 中的行业映射。<br>
        2. 行业收益 = 该行业下所有有行情股票的日收益率等权平均；剔除股票数少于 {{min_stocks}} 的行业。<br>
        3. 相关性 = 行业日收益率序列的 Pearson 相关系数；热力图按贪心排序（高相关板块相邻）重新排列。<br>
        4. 报告生成时间：{{generated_at}}。
      </p>
    </div>
  </div>

  <script>
    const labels = {{labels_json}};
    const z = {{z_json}};
    const cumSeries = {{cum_series_json}};

    // Heatmap
    const heatmapData = [{
      z: z,
      x: labels,
      y: labels,
      type: 'heatmap',
      colorscale: [
        [0, '#198754'],
        [0.5, '#ffffff'],
        [1, '#dc3545']
      ],
      zmin: -1,
      zmax: 1,
      text: z.map(row => row.map(v => v.toFixed(2))),
      hovertemplate: '%{x} vs %{y}<br>相关系数: %{z:.3f}<extra></extra>',
      colorbar: { title: '相关系数' }
    }];

    // Fixed-size heatmap: each cell is at least 24 px so all 45 labels remain
    // readable. The page scrolls horizontally when the viewport is narrower.
    const cellSize = 24;
    const margin = 180;
    const heatmapSize = labels.length * cellSize + margin * 2;

    const heatmapLayout = {
      width: heatmapSize,
      height: heatmapSize,
      margin: { l: margin, b: margin, t: 40, r: 80 },
      xaxis: { tickangle: -45, tickfont: { size: 11 } },
      yaxis: { autorange: 'reversed', tickfont: { size: 11 } },
      title: { text: '行业板块日收益率相关系数矩阵', x: 0.5 }
    };

    Plotly.newPlot('heatmap', heatmapData, heatmapLayout);

    // Cumulative returns
    const colors = [
      '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b',
      '#e377c2', '#7f7f7f', '#bcbd22', '#17becf', '#aec7e8', '#ffbb78',
      '#98df8a', '#ff9896', '#c5b0d5', '#c49c94', '#f7b6d2', '#c7c7c7'
    ];
    const returnTraces = Object.entries(cumSeries).map(([name, data], i) => ({
      x: data.x,
      y: data.y,
      mode: 'lines',
      name: name,
      line: { width: 2, color: colors[i % colors.length] }
    }));
    Plotly.newPlot('returns-chart', returnTraces, {
      margin: { l: 60, r: 20, t: 20, b: 40 },
      xaxis: { title: '日期' },
      yaxis: { title: '累计净值（起点=100）' },
      hovermode: 'x unified',
      legend: { orientation: 'h', y: -0.25 }
    }, {responsive: true});
  </script>
</body>
</html>
"""

    def fmt_corr(v: float) -> str:
        cls = "corr-pos" if v >= 0 else "corr-neg"
        return f'<span class="{cls}">{v:+.3f}</span>'

    def rows_html(df: pd.DataFrame) -> str:
        rows = []
        for _, r in df.iterrows():
            rows.append(
                f"<tr><td>{shorten_industry(r['industry_a'])}</td>"
                f"<td>{shorten_industry(r['industry_b'])}</td>"
                f"<td>{fmt_corr(r['corr'])}</td></tr>"
            )
        return "\n".join(rows)

    def single_rows_html(df: pd.DataFrame) -> str:
        rows = []
        for _, r in df.iterrows():
            rows.append(
                f"<tr><td>{shorten_industry(r['industry'])}</td>"
                f"<td>{fmt_corr(r['corr'])}</td></tr>"
            )
        return "\n".join(rows)

    generated_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    html = template
    html = html.replace("{{date_range}}", summary["date_range"])
    html = html.replace("{{n_industries}}", str(summary["n_industries"]))
    html = html.replace("{{n_trading_days}}", str(summary["n_trading_days"]))
    html = html.replace("{{mean_abs_corr}}", f"{summary['mean_abs_corr']:.3f}")
    html = html.replace("{{max_corr}}", f"{summary['max_corr']:+.3f}")
    html = html.replace("{{min_corr}}", f"{summary['min_corr']:+.3f}")
    html = html.replace("{{min_stocks}}", str(MIN_STOCKS_PER_INDUSTRY))
    html = html.replace("{{generated_at}}", generated_at)
    html = html.replace("{{labels_json}}", json.dumps(short_labels, ensure_ascii=False))
    html = html.replace("{{z_json}}", json.dumps(z, ensure_ascii=False))
    html = html.replace("{{cum_series_json}}", json.dumps(cum_series, ensure_ascii=False))
    html = html.replace("{{positive_rows}}", rows_html(positive))
    html = html.replace("{{negative_rows}}", rows_html(negative))
    html = html.replace("{{strongest_rows}}", rows_html(strongest))
    if bank_corr is not None:
        bank_pos, bank_neg, bank_full = bank_corr
        html = html.replace("{{banking_positive_rows}}", single_rows_html(bank_pos))
        html = html.replace("{{banking_negative_rows}}", single_rows_html(bank_neg))
        html = html.replace("{{banking_full_rows}}", single_rows_html(bank_full))
    else:
        no_data = "<tr><td colspan=2>无银行业数据</td></tr>"
        html = html.replace("{{banking_positive_rows}}", no_data)
        html = html.replace("{{banking_negative_rows}}", no_data)
        html = html.replace("{{banking_full_rows}}", no_data)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def main() -> int:
    print("Loading stock quotes and industry mapping...")
    df, max_date, start_date = load_data()
    print(f"Loaded {len(df):,} rows, date range {start_date} ~ {max_date}")

    print("Building industry return series...")
    returns = build_industry_returns(df)
    print(f"Industries with enough data: {len(returns.columns)}")

    print("Computing correlation matrix...")
    corr = compute_correlation_matrix(returns)

    output_path = REPORT_DIR / "industry_correlation_report.html"
    print(f"Generating report: {output_path}")
    generate_html(corr, returns, max_date, start_date, output_path)

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
