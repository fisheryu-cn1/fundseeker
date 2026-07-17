"""CLI entry point for the similarity service.

Examples:
    PYTHONPATH=src python -m fundseeker.similarity.cli cluster \
        --report-date 2026-03-31 --k auto

    PYTHONPATH=src python -m fundseeker.similarity.cli cluster \
        --report-date 2026-03-31 --feature-type industry --k auto

    PYTHONPATH=src python -m fundseeker.similarity.cli refresh-industries

    PYTHONPATH=src python -m fundseeker.similarity.cli refresh-quotes \
        --report-date 2026-03-31 --start-date 2026-04-01 --end-date 2026-07-10

    PYTHONPATH=src python -m fundseeker.similarity.cli attribution \
        --report-date 2026-03-31 --cluster-id 0 \
        --start-date 2026-04-01 --end-date 2026-07-10

    PYTHONPATH=src python -m fundseeker.similarity.cli neighbors \
        --product-id 117661 --report-date 2026-03-31 --top-n 10

    PYTHONPATH=src python -m fundseeker.similarity.cli list \
        --report-date 2026-03-31 --algorithm kmeans-industry
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

from fundseeker.similarity.industry import update_security_industries
from fundseeker.similarity.service import SimilarityService


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _format_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _parse_product_types(value: str | None) -> tuple[str, ...] | None:
    if not value:
        return None
    parts = tuple(v.strip() for v in value.split(",") if v.strip())
    return parts if parts else None


def cmd_cluster(args: argparse.Namespace) -> int:
    svc = SimilarityService()
    result = svc.cluster(
        report_date=args.report_date,
        product_types=_parse_product_types(args.product_types),
        k=args.k,
        save=not args.no_save,
        feature_type=args.feature_type,
    )
    print(_format_json(result))
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    svc = SimilarityService()
    profile = svc.get_cluster_profile(
        cluster_id=args.cluster_id,
        report_date=args.report_date,
        algorithm=args.algorithm,
        k=args.k,
    )
    print(_format_json(profile))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    svc = SimilarityService()
    run = svc.list_clusters(
        report_date=args.report_date,
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
                "avg_overlap": c["avg_overlap"],
                "avg_overlap_raw": c["avg_overlap_raw"],
                "ac_share_dominance_ratio": c["ac_share_dominance_ratio"],
                "top_industries": (c["top_industries"] or c["top_holdings"])[:5],
                "representative_codes": c["representative_codes"][:3],
            }
            for c in run["clusters"]
        ],
    }
    print(_format_json(summary))
    return 0


def cmd_refresh_industries(args: argparse.Namespace) -> int:
    stats = update_security_industries(dry_run=args.dry_run)
    print(_format_json(stats))
    return 0


def cmd_refresh_quotes(args: argparse.Namespace) -> int:
    svc = SimilarityService()
    stats = svc.refresh_quotes(
        report_date=args.report_date,
        start_date=args.start_date,
        end_date=args.end_date,
        dry_run=args.dry_run,
    )
    print(_format_json(stats))
    return 0


def cmd_attribution(args: argparse.Namespace) -> int:
    svc = SimilarityService()
    if args.all_clusters:
        result = svc.attribute_run(
            report_date=args.report_date,
            start_date=args.start_date,
            end_date=args.end_date,
            algorithm=args.algorithm,
            k=args.k,
            benchmark=args.benchmark,
            benchmark_code=args.benchmark_code,
            save=not args.no_save,
        )
    else:
        result = svc.attribute_cluster(
            cluster_id=args.cluster_id,
            report_date=args.report_date,
            start_date=args.start_date,
            end_date=args.end_date,
            algorithm=args.algorithm,
            k=args.k,
            benchmark=args.benchmark,
            benchmark_code=args.benchmark_code,
            save=not args.no_save,
        )
    print(_format_json(result))
    return 0


def cmd_refresh_index_weights(args: argparse.Namespace) -> int:
    from fundseeker.similarity.index_weights import refresh_index_weights

    stats = refresh_index_weights(
        index_codes=args.index_codes.split(",") if args.index_codes else None,
        dry_run=args.dry_run,
    )
    print(_format_json(stats))
    return 0


def cmd_neighbors(args: argparse.Namespace) -> int:
    svc = SimilarityService()
    result = svc.find_neighbors(
        product_id=args.product_id,
        report_date=args.report_date,
        top_n=args.top_n,
        metric=args.metric,
        product_types=_parse_product_types(args.product_types),
        feature_type=args.feature_type,
    )
    print(_format_json(result))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fundseeker.similarity",
        description="Portfolio similarity analysis CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_cluster = subparsers.add_parser("cluster", help="Run clustering for a report date")
    p_cluster.add_argument("--report-date", type=_parse_date, required=True)
    p_cluster.add_argument(
        "--product-types",
        type=str,
        default="equity,mixed",
        help="Comma-separated product types (default: equity,mixed)",
    )
    p_cluster.add_argument(
        "--k",
        type=str,
        default="auto",
        help="Number of clusters or 'auto' (default: auto)",
    )
    p_cluster.add_argument(
        "--feature-type",
        type=str,
        choices=["asset", "industry"],
        default="asset",
        help="Feature space for clustering (default: asset)",
    )
    p_cluster.add_argument(
        "--no-save",
        action="store_true",
        help="Do not persist results to the database",
    )
    p_cluster.set_defaults(func=cmd_cluster)

    p_profile = subparsers.add_parser("profile", help="Show cluster profile")
    p_profile.add_argument("--report-date", type=_parse_date, required=True)
    p_profile.add_argument("--cluster-id", type=int, required=True)
    p_profile.add_argument("--algorithm", type=str, default="kmeans-asset")
    p_profile.add_argument("--k", type=int, default=None)
    p_profile.set_defaults(func=cmd_profile)

    p_list = subparsers.add_parser("list", help="List all clusters for a report date")
    p_list.add_argument("--report-date", type=_parse_date, required=True)
    p_list.add_argument("--algorithm", type=str, default="kmeans-asset")
    p_list.add_argument("--k", type=int, default=None)
    p_list.set_defaults(func=cmd_list)

    p_refresh = subparsers.add_parser(
        "refresh-industries",
        help="Refresh industry mapping in holding_security_info",
    )
    p_refresh.add_argument(
        "--dry-run",
        action="store_true",
        help="Count updates without writing",
    )
    p_refresh.set_defaults(func=cmd_refresh_industries)

    p_quotes = subparsers.add_parser(
        "refresh-quotes",
        help="Backfill stock quotes for holdings of a report date",
    )
    p_quotes.add_argument("--report-date", type=_parse_date, required=True)
    p_quotes.add_argument(
        "--start-date",
        type=_parse_date,
        default=None,
        help="Start date (default: report_date)",
    )
    p_quotes.add_argument(
        "--end-date",
        type=_parse_date,
        default=None,
        help="End date (default: today)",
    )
    p_quotes.add_argument(
        "--dry-run",
        action="store_true",
        help="Count quotes without writing",
    )
    p_quotes.set_defaults(func=cmd_refresh_quotes)

    p_attr = subparsers.add_parser(
        "attribution",
        help="Run Brinson attribution for products in a cluster or a full run",
    )
    p_attr.add_argument("--report-date", type=_parse_date, required=True)
    p_attr.add_argument("--cluster-id", type=int, default=None)
    p_attr.add_argument(
        "--all-clusters",
        action="store_true",
        help="Attribute every cluster in the selected run",
    )
    p_attr.add_argument("--start-date", type=_parse_date, required=True)
    p_attr.add_argument("--end-date", type=_parse_date, required=True)
    p_attr.add_argument("--algorithm", type=str, default="kmeans-asset")
    p_attr.add_argument("--k", type=int, default=None)
    p_attr.add_argument(
        "--benchmark",
        type=str,
        choices=["cluster_avg", "index"],
        default="cluster_avg",
        help="Benchmark type (default: cluster_avg)",
    )
    p_attr.add_argument(
        "--benchmark-code",
        type=str,
        default=None,
        help="Index code for index benchmark, e.g. 000300 / 000906",
    )
    p_attr.add_argument(
        "--no-save",
        action="store_true",
        help="Do not persist results to the database",
    )
    p_attr.set_defaults(func=cmd_attribution)

    p_idx = subparsers.add_parser(
        "refresh-index-weights",
        help="Fetch and store index constituent weights from CSI",
    )
    p_idx.add_argument(
        "--index-codes",
        type=str,
        default="000300,000906",
        help="Comma-separated CSI index codes (default: 000300,000906)",
    )
    p_idx.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows without writing",
    )
    p_idx.set_defaults(func=cmd_refresh_index_weights)

    p_neighbors = subparsers.add_parser(
        "neighbors",
        help="Find most similar products to a given product",
    )
    p_neighbors.add_argument("--product-id", type=int, required=True)
    p_neighbors.add_argument("--report-date", type=_parse_date, required=True)
    p_neighbors.add_argument("--top-n", type=int, default=10)
    p_neighbors.add_argument(
        "--metric",
        type=str,
        choices=["overlap", "cosine", "jaccard"],
        default="overlap",
    )
    p_neighbors.add_argument(
        "--product-types",
        type=str,
        default="equity,mixed",
        help="Comma-separated product types (default: equity,mixed)",
    )
    p_neighbors.add_argument(
        "--feature-type",
        type=str,
        choices=["asset", "industry"],
        default="asset",
    )
    p_neighbors.set_defaults(func=cmd_neighbors)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
