#!/usr/bin/env python3
"""CLI core implementation for portfolio similarity analysis.

This module is imported by both ``scripts/fundseeker_similarity.py`` (the
official standalone CLI) and ``src/fundseeker/similarity/cli.py`` (the
legacy module entry point).  New code should call
``scripts/fundseeker_similarity.py`` directly.

Typical usage:

    PYTHONPATH=src python scripts/fundseeker_similarity.py cluster \
        --report-date 2026-03-31 --k auto

    PYTHONPATH=src python scripts/fundseeker_similarity.py pipeline \
        --report-date 2026-03-31 --start-date 2026-04-01 --end-date today
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root / "src"))

from sqlalchemy import func, select

from fundseeker.models.database import get_engine
from fundseeker.models.tables import ProductHolding
from fundseeker.similarity.industry import update_security_industries
from fundseeker.similarity.index_weights import refresh_index_weights
from fundseeker.similarity.service import SimilarityService


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _parse_product_types(value: str | None) -> tuple[str, ...] | None:
    if not value:
        return None
    parts = tuple(v.strip() for v in value.split(",") if v.strip())
    return parts if parts else None


def _today() -> date:
    return date.today()


def _resolve_date(value: str | None) -> date:
    if value is None or value.lower() in ("today", "now"):
        return _today()
    return _parse_date(value)


def _latest_report_date(engine: Any) -> date:
    with engine.connect() as conn:
        row = conn.execute(
            select(func.max(ProductHolding.report_date))
        ).scalar_one_or_none()
    if row is None:
        raise RuntimeError("数据库中不存在任何持仓报告期，无法自动确定 --report-date")
    return row


def _fmt_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _parse_k(value: str) -> int | str:
    return int(value) if value.isdigit() else value


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_cluster(args: argparse.Namespace, svc: SimilarityService) -> int:
    report_date = args.report_date or _latest_report_date(get_engine())
    result = svc.cluster(
        report_date=report_date,
        product_types=_parse_product_types(args.product_types),
        k=_parse_k(args.k),
        save=not args.no_save,
        feature_type=args.feature_type,
        mode=args.mode,
    )
    print(_fmt_json(result))
    return 0


def cmd_attribution(args: argparse.Namespace, svc: SimilarityService) -> int:
    report_date = args.report_date or _latest_report_date(get_engine())
    start_date = _resolve_date(args.start_date)
    end_date = _resolve_date(args.end_date)

    if args.all_clusters:
        result = svc.attribute_run(
            report_date=report_date,
            start_date=start_date,
            end_date=end_date,
            algorithm=args.algorithm,
            k=args.k,
            benchmark=args.benchmark,
            benchmark_code=args.benchmark_code,
            save=not args.no_save,
        )
    else:
        if args.cluster_id is None:
            print(
                "错误：必须指定 --cluster-id 或 --all-clusters",
                file=sys.stderr,
            )
            return 2
        result = svc.attribute_cluster(
            cluster_id=args.cluster_id,
            report_date=report_date,
            start_date=start_date,
            end_date=end_date,
            algorithm=args.algorithm,
            k=args.k,
            benchmark=args.benchmark,
            benchmark_code=args.benchmark_code,
            save=not args.no_save,
        )
    print(_fmt_json(result))
    return 0


def cmd_list(args: argparse.Namespace, svc: SimilarityService) -> int:
    report_date = args.report_date or _latest_report_date(get_engine())
    run = svc.list_clusters(
        report_date=report_date,
        algorithm=args.algorithm,
        k=args.k,
    )
    summary = {
        "cluster_run_id": run["cluster_run_id"],
        "report_date": run["report_date"],
        "algorithm": run["algorithm"],
        "k": run["k"],
        "total_members": len(run["members"]),
        "clusters": [
            {
                "cluster_id": c["cluster_id"],
                "size": c["size"],
                "cluster_label": c.get("cluster_label"),
                "avg_overlap": c["avg_overlap"],
                "avg_overlap_raw": c["avg_overlap_raw"],
                "top_industries": (c["top_industries"] or [])[:5],
                "top_holdings": (c["top_holdings"] or [])[:5],
                "representative_codes": (c["representative_codes"] or [])[:3],
            }
            for c in run["clusters"]
        ],
    }
    print(_fmt_json(summary))
    return 0


def cmd_list_baselines(
    args: argparse.Namespace, svc: SimilarityService
) -> int:
    report_date = args.report_date
    baselines = svc.list_baselines(
        report_date=report_date,
        algorithm=args.algorithm,
        feature_type=args.feature_type,
    )
    print(_fmt_json(baselines))
    return 0


def cmd_profile(args: argparse.Namespace, svc: SimilarityService) -> int:
    report_date = args.report_date or _latest_report_date(get_engine())
    profile = svc.get_cluster_profile(
        cluster_id=args.cluster_id,
        report_date=report_date,
        algorithm=args.algorithm,
        k=args.k,
    )
    print(_fmt_json(profile))
    return 0


def cmd_neighbors(args: argparse.Namespace, svc: SimilarityService) -> int:
    report_date = args.report_date or _latest_report_date(get_engine())
    result = svc.find_neighbors(
        product_id=args.product_id,
        report_date=report_date,
        top_n=args.top_n,
        metric=args.metric,
        product_types=_parse_product_types(args.product_types),
        feature_type=args.feature_type,
    )
    print(_fmt_json(result))
    return 0


def cmd_refresh_quotes(args: argparse.Namespace, svc: SimilarityService) -> int:
    report_date = args.report_date or _latest_report_date(get_engine())
    start_date = _resolve_date(args.start_date) if args.start_date else None
    end_date = _resolve_date(args.end_date) if args.end_date else None
    stats = svc.refresh_quotes(
        report_date=report_date,
        start_date=start_date,
        end_date=end_date,
        dry_run=args.dry_run,
    )
    print(_fmt_json(stats))
    return 0


def cmd_refresh_index_weights(
    args: argparse.Namespace, _svc: SimilarityService
) -> int:
    stats = refresh_index_weights(
        index_codes=args.index_codes.split(",") if args.index_codes else None,
        dry_run=args.dry_run,
    )
    print(_fmt_json(stats))
    return 0


def cmd_refresh_industries(
    args: argparse.Namespace, _svc: SimilarityService
) -> int:
    stats = update_security_industries(dry_run=args.dry_run)
    print(_fmt_json(stats))
    return 0


def cmd_pipeline(args: argparse.Namespace, svc: SimilarityService) -> int:
    """Run the full similarity analysis pipeline for scheduled execution."""
    report_date = args.report_date or _latest_report_date(get_engine())
    start_date = _resolve_date(args.start_date)
    end_date = _resolve_date(args.end_date)
    results: dict[str, Any] = {
        "report_date": report_date.isoformat(),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }

    # 1. Refresh index weights (lightweight, idempotent)
    if not args.skip_index_weights:
        results["index_weights"] = refresh_index_weights(
            index_codes=args.index_codes.split(",") if args.index_codes else None,
        )

    # 2. Refresh stock quotes for holdings in the report date
    if not args.skip_quotes:
        results["quotes"] = svc.refresh_quotes(
            report_date=report_date,
            start_date=start_date,
            end_date=end_date,
        )

    # 3. Run clustering
    cluster_k: int | None = None
    if not args.skip_cluster:
        cluster_result = svc.cluster(
            report_date=report_date,
            product_types=_parse_product_types(args.product_types),
            k=_parse_k(args.k),
            save=True,
            feature_type=args.feature_type,
            mode=args.mode,
        )
        cluster_k = cluster_result["k"]
        results["cluster"] = {
            "cluster_run_id": cluster_result["cluster_run_id"],
            "report_date": cluster_result["report_date"],
            "algorithm": cluster_result["algorithm"],
            "k": cluster_result["k"],
            "feature_type": cluster_result["feature_type"],
            "n_products": cluster_result["n_products"],
            "n_features": cluster_result["n_features"],
            "silhouette": cluster_result["silhouette"],
            "inertia": cluster_result["inertia"],
            "n_iter": cluster_result["n_iter"],
            "mode": cluster_result["mode"],
            "baseline_run_id": cluster_result["baseline_run_id"],
            "k_search_results": cluster_result.get("k_search_results"),
            "incremental_diagnostics": cluster_result.get("incremental_diagnostics"),
        }
    else:
        # When clustering is skipped, resolve k for attribution.
        parsed = _parse_k(args.k)
        cluster_k = parsed if isinstance(parsed, int) else None

    # 4. Run attribution for all clusters
    if not args.skip_attribution:
        attribution_result = svc.attribute_run(
            report_date=report_date,
            start_date=start_date,
            end_date=end_date,
            algorithm=args.algorithm,
            k=cluster_k,
            benchmark=args.benchmark,
            benchmark_code=args.benchmark_code,
            save=True,
        )
        results["attribution"] = {
            "cluster_run_id": attribution_result["cluster_run_id"],
            "clusters_attributed": attribution_result["clusters_attributed"],
            "total_products": attribution_result["total_products"],
            "benchmark": attribution_result["benchmark"],
            "benchmark_code": attribution_result["benchmark_code"],
        }

    print(_fmt_json(results))
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fundseeker_similarity",
        description="产品持仓相似性分析与聚类处理 CLI（独立于采集/查询 CLI）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Common options reused by several subcommands
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--report-date",
        type=_parse_date,
        default=None,
        help="持仓报告期（YYYY-MM-DD），默认取数据库最新报告期",
    )

    algo_common = argparse.ArgumentParser(add_help=False)
    algo_common.add_argument(
        "--algorithm",
        type=str,
        default="kmeans-asset",
        help="聚类算法标识（默认: kmeans-asset）",
    )
    algo_common.add_argument(
        "--k",
        type=int,
        default=None,
        help="聚类数 k（默认从已保存的运行中读取）",
    )

    attr_common = argparse.ArgumentParser(add_help=False)
    attr_common.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="归因起始日（YYYY-MM-DD 或 today）",
    )
    attr_common.add_argument(
        "--end-date",
        type=str,
        required=True,
        help="归因截止日（YYYY-MM-DD 或 today）",
    )
    attr_common.add_argument(
        "--benchmark",
        type=str,
        choices=["cluster_avg", "index"],
        default="cluster_avg",
        help="基准类型（默认: cluster_avg）",
    )
    attr_common.add_argument(
        "--benchmark-code",
        type=str,
        default=None,
        help="指数基准代码，如 000300 / 000906（benchmark=index 时必填）",
    )
    attr_common.add_argument(
        "--no-save",
        action="store_true",
        help="不将结果写入数据库（仅打印）",
    )

    # cluster
    sp = sub.add_parser(
        "cluster",
        parents=[common],
        help="对指定报告期执行持仓聚类",
    )
    sp.add_argument(
        "--product-types",
        type=str,
        default="equity,mixed",
        help="参与聚类的产品类型，逗号分隔（默认: equity,mixed）",
    )
    sp.add_argument(
        "--k",
        type=str,
        default="auto",
        help="聚类数或 auto（默认: auto）",
    )
    sp.add_argument(
        "--feature-type",
        type=str,
        choices=["asset", "industry"],
        default="asset",
        help="特征空间（默认: asset）",
    )
    sp.add_argument(
        "--no-save",
        action="store_true",
        help="不将结果写入数据库（仅打印）",
    )
    sp.add_argument(
        "--mode",
        type=str,
        choices=["auto", "full", "incremental"],
        default="auto",
        help=(
            "聚类模式：auto 无基线时走全量、有基线时尝试增量；"
            "full 始终全量并更新基线；incremental 要求已有基线（默认: auto）"
        ),
    )
    sp.set_defaults(func=cmd_cluster)

    # attribution
    sp = sub.add_parser(
        "attribution",
        parents=[common, algo_common, attr_common],
        help="对指定簇或全部簇执行 Brinson 归因",
    )
    sp.add_argument("--cluster-id", type=int, default=None, help="簇编号")
    sp.add_argument(
        "--all-clusters",
        action="store_true",
        help="对运行中的所有簇执行归因",
    )
    sp.set_defaults(func=cmd_attribution)

    # list
    sp = sub.add_parser(
        "list",
        parents=[common, algo_common],
        help="列出指定报告期的所有簇",
    )
    sp.set_defaults(func=cmd_list)

    # list-baselines
    sp = sub.add_parser(
        "list-baselines",
        parents=[common],
        help="列出已保存的聚类基线",
    )
    sp.add_argument(
        "--algorithm",
        type=str,
        default=None,
        help="按算法标识过滤，如 kmeans-asset",
    )
    sp.add_argument(
        "--feature-type",
        type=str,
        choices=["asset", "industry"],
        default=None,
        help="按特征类型过滤",
    )
    sp.set_defaults(func=cmd_list_baselines)

    # profile
    sp = sub.add_parser(
        "profile",
        parents=[common, algo_common],
        help="查看指定簇的画像详情",
    )
    sp.add_argument("--cluster-id", type=int, required=True, help="簇编号")
    sp.set_defaults(func=cmd_profile)

    # neighbors
    sp = sub.add_parser(
        "neighbors",
        parents=[common],
        help="查找与指定产品最相似的产品",
    )
    sp.add_argument("--product-id", type=int, required=True, help="产品 ID")
    sp.add_argument("--top-n", type=int, default=10, help="返回数量（默认: 10）")
    sp.add_argument(
        "--metric",
        type=str,
        choices=["overlap", "cosine", "jaccard"],
        default="overlap",
        help="相似度指标（默认: overlap）",
    )
    sp.add_argument(
        "--product-types",
        type=str,
        default="equity,mixed",
        help="候选产品类型，逗号分隔（默认: equity,mixed）",
    )
    sp.add_argument(
        "--feature-type",
        type=str,
        choices=["asset", "industry"],
        default="asset",
        help="特征空间（默认: asset）",
    )
    sp.set_defaults(func=cmd_neighbors)

    # refresh-quotes
    sp = sub.add_parser(
        "refresh-quotes",
        parents=[common],
        help="补录持仓涉及个股的日行情",
    )
    sp.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="起始日（默认: report_date）",
    )
    sp.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="截止日（默认: today）",
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计需补录数量，不写入",
    )
    sp.set_defaults(func=cmd_refresh_quotes)

    # refresh-index-weights
    sp = sub.add_parser(
        "refresh-index-weights",
        help="从中证官网采集指数成分股权重",
    )
    sp.add_argument(
        "--index-codes",
        type=str,
        default="000300,000906",
        help="指数代码，逗号分隔（默认: 000300,000906）",
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计，不写入",
    )
    sp.set_defaults(func=cmd_refresh_index_weights)

    # refresh-industries
    sp = sub.add_parser(
        "refresh-industries",
        help="刷新持仓证券的行业映射",
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计，不写入",
    )
    sp.set_defaults(func=cmd_refresh_industries)

    # pipeline
    sp = sub.add_parser(
        "pipeline",
        parents=[common],
        help="执行完整分析流水线：行情补录 → 聚类 → 归因",
    )
    sp.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="归因起始日（YYYY-MM-DD 或 today）",
    )
    sp.add_argument(
        "--end-date",
        type=str,
        required=True,
        help="归因截止日（YYYY-MM-DD 或 today）",
    )
    sp.add_argument(
        "--product-types",
        type=str,
        default="equity,mixed",
        help="参与聚类的产品类型（默认: equity,mixed）",
    )
    sp.add_argument(
        "--k",
        type=str,
        default="auto",
        help="聚类数或 auto（默认: auto）",
    )
    sp.add_argument(
        "--feature-type",
        type=str,
        choices=["asset", "industry"],
        default="asset",
        help="特征空间（默认: asset）",
    )
    sp.add_argument(
        "--algorithm",
        type=str,
        default="kmeans-asset",
        help="聚类算法标识（默认: kmeans-asset）",
    )
    sp.add_argument(
        "--benchmark",
        type=str,
        choices=["cluster_avg", "index"],
        default="cluster_avg",
        help="归因基准类型（默认: cluster_avg）",
    )
    sp.add_argument(
        "--benchmark-code",
        type=str,
        default=None,
        help="指数基准代码（benchmark=index 时必填）",
    )
    sp.add_argument(
        "--index-codes",
        type=str,
        default="000300,000906",
        help="要刷新的指数代码（默认: 000300,000906）",
    )
    sp.add_argument(
        "--skip-index-weights",
        action="store_true",
        help="跳过指数权重刷新",
    )
    sp.add_argument(
        "--skip-quotes",
        action="store_true",
        help="跳过行情补录",
    )
    sp.add_argument(
        "--skip-cluster",
        action="store_true",
        help="跳过聚类（使用已有运行）",
    )
    sp.add_argument(
        "--skip-attribution",
        action="store_true",
        help="跳过归因",
    )
    sp.add_argument(
        "--mode",
        type=str,
        choices=["auto", "full", "incremental"],
        default="auto",
        help=(
            "聚类模式：auto 无基线时走全量、有基线时尝试增量；"
            "full 始终全量并更新基线；incremental 要求已有基线（默认: auto）"
        ),
    )
    sp.set_defaults(func=cmd_pipeline)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    svc = SimilarityService()
    try:
        return args.func(args, svc)
    except Exception as exc:
        print(f"执行失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
