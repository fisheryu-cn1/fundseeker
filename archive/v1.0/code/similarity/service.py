"""Unified service API for the similarity package."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from fundseeker.similarity.attribution import attribute_products
from fundseeker.similarity.index_weights import load_index_weights
from fundseeker.similarity.clustering import KMeansResult, select_k_silhouette
from fundseeker.similarity.config import DEFAULT_CONFIG, SimilarityConfig
from fundseeker.similarity.data import HoldingData, load_holdings
from fundseeker.similarity.features import (
    FeatureMatrix,
    build_industry_matrix,
    build_weight_matrix,
)
from fundseeker.similarity.industry import (
    IndustryMapping,
    fetch_industry_mapping,
    load_industry_mapping_from_db,
)
from fundseeker.similarity.profiling import ClusterProfile, build_profiles
from fundseeker.similarity.persistence import (
    load_cluster_run,
    save_attribution,
    save_cluster_run,
)
from fundseeker.similarity.quotes import refresh_stock_quotes
from fundseeker.similarity.similarity import find_neighbors


class SimilarityService:
    """High-level service for portfolio similarity analysis.

    The service is stateless and read-only with respect to raw data tables.
    Computation results are persisted to dedicated similarity_* tables.
    """

    def __init__(self, config: SimilarityConfig | None = None):
        self.config = config or DEFAULT_CONFIG
        self._industry_mapping: IndustryMapping | None = None

    def _get_industry_mapping(
        self, use_db: bool = True, force_refresh: bool = False
    ) -> IndustryMapping:
        """Lazy-load industry mapping, preferring the local DB.

        Args:
            use_db: Whether to try loading from holding_security_info first.
            force_refresh: If True, refetch from Eastmoney and repopulate DB.
        """
        if self._industry_mapping is None or force_refresh:
            if use_db and not force_refresh:
                self._industry_mapping = load_industry_mapping_from_db()
            else:
                self._industry_mapping = fetch_industry_mapping()
        return self._industry_mapping

    def build_features(
        self,
        report_date: date | str,
        product_types: tuple[str, ...] | list[str] | None = None,
        asset_types: tuple[str, ...] | list[str] | None = None,
        min_holdings: int | None = None,
        deduplicate: bool = True,
        normalize: bool | None = None,
        feature_type: str = "asset",
    ) -> FeatureMatrix:
        """Load holdings and build a weight matrix.

        Args:
            report_date: Target report date.
            product_types: Product types to include.
            asset_types: Asset types to use.
            min_holdings: Minimum holdings per product.
            deduplicate: Whether to merge A/C share classes.
            normalize: Whether to L2-normalize vectors.
            feature_type: "asset" or "industry".

        Returns:
            FeatureMatrix with assets or industries as columns.
        """
        cfg = self.config.cluster
        product_types = product_types or cfg.product_types
        asset_types = asset_types or cfg.asset_types
        min_holdings = min_holdings if min_holdings is not None else cfg.min_holdings
        normalize = normalize if normalize is not None else cfg.normalize

        data = load_holdings(
            report_date=report_date,
            product_types=product_types,
            asset_types=asset_types,
            min_holdings=min_holdings,
        )

        if feature_type == "industry":
            mapping = self._get_industry_mapping()
            return build_industry_matrix(
                data,
                mapping=mapping,
                deduplicate=deduplicate,
                normalize=normalize,
            )
        if feature_type == "asset":
            return build_weight_matrix(
                data,
                deduplicate=deduplicate,
                normalize=normalize,
            )
        raise ValueError(f"Unknown feature_type: {feature_type}")

    def cluster(
        self,
        report_date: date | str,
        product_types: tuple[str, ...] | list[str] | None = None,
        k: int | str | None = None,
        save: bool = True,
        feature_type: str = "asset",
    ) -> dict[str, Any]:
        """Run clustering for a report date.

        Args:
            report_date: Target report date.
            product_types: Product types to include.
            k: Number of clusters or "auto".
            save: Whether to persist results to the database.
            feature_type: "asset" or "industry".

        Returns:
            Dict with feature matrix, clustering result, profiles and metadata.
        """
        cfg = self.config.cluster
        product_types = product_types or cfg.product_types
        k = k if k is not None else cfg.k

        fm = self.build_features(
            report_date,
            product_types=product_types,
            feature_type=feature_type,
        )

        if k == "auto":
            selection = select_k_silhouette(
                fm.X,
                k_min=cfg.k_min,
                k_max=cfg.k_max,
                seed=cfg.random_seed,
                max_iter=cfg.max_iter,
                tol=cfg.tol,
            )
            result = selection["best_result"]
            k_value = selection["best_k"]
            k_search_results = selection["results"]
        else:
            k_value = int(k)
            from fundseeker.similarity.clustering import kmeans
            result = kmeans(
                fm.X,
                k=k_value,
                seed=cfg.random_seed,
                max_iter=cfg.max_iter,
                tol=cfg.tol,
            )
            k_search_results = None

        mapping = self._get_industry_mapping() if feature_type == "asset" else None
        profiles = build_profiles(fm, result, mapping=mapping)

        product_type_filter = ",".join(product_types)
        algorithm = f"{cfg.algorithm}-{feature_type}"
        params = {
            **self.config.to_dict()["cluster"],
            "feature_type": feature_type,
            "report_date": str(fm.report_date),
        }

        cluster_run_id = None
        if save:
            cluster_run_id = save_cluster_run(
                report_date=fm.report_date,
                product_type_filter=product_type_filter,
                algorithm=algorithm,
                k=k_value,
                params=params,
                fm=fm,
                result=result,
                profiles=profiles,
            )

        return {
            "cluster_run_id": cluster_run_id,
            "report_date": fm.report_date,
            "algorithm": algorithm,
            "k": k_value,
            "feature_type": feature_type,
            "n_products": fm.n_products,
            "n_features": fm.n_features,
            "silhouette": result.silhouette,
            "inertia": result.inertia,
            "n_iter": result.n_iter,
            "k_search_results": k_search_results,
            "profiles": [self._profile_to_dict(p) for p in profiles],
        }

    def get_cluster_profile(
        self,
        cluster_id: int,
        report_date: date | str,
        algorithm: str = "kmeans-asset",
        k: int | None = None,
        product_type_filter: str | None = None,
    ) -> dict[str, Any]:
        """Load a cluster profile from a persisted run."""
        run = load_cluster_run(
            report_date,
            algorithm=algorithm,
            k=k,
            product_type_filter=product_type_filter,
        )
        for c in run["clusters"]:
            if c["cluster_id"] == cluster_id:
                return c
        raise ValueError(
            f"Cluster {cluster_id} not found for report_date={report_date}, "
            f"algorithm={algorithm}, k={run['k']}"
        )

    def list_clusters(
        self,
        report_date: date | str,
        algorithm: str = "kmeans-asset",
        k: int | None = None,
        product_type_filter: str | None = None,
    ) -> dict[str, Any]:
        """Load all clusters for a report date."""
        return load_cluster_run(
            report_date,
            algorithm=algorithm,
            k=k,
            product_type_filter=product_type_filter,
        )

    def refresh_quotes(
        self,
        report_date: date | str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: list[tuple[str, str, str | None]] | None = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Backfill stock quotes for holdings of ``report_date``.

        This is a data-prep utility; the similarity service is otherwise
        read-only with respect to raw data tables.
        """
        return refresh_stock_quotes(
            report_date=report_date,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            dry_run=dry_run,
        )

    def find_neighbors(
        self,
        product_id: int,
        report_date: date | str,
        top_n: int = 10,
        metric: str = "overlap",
        product_types: tuple[str, ...] | list[str] | None = None,
        feature_type: str = "asset",
    ) -> dict[str, Any]:
        """Find the most similar products to a given product.

        Args:
            product_id: Target product id.
            report_date: Holding report date.
            top_n: Number of neighbors to return.
            metric: Similarity metric: overlap / cosine / jaccard.
            product_types: Product types to include.
            feature_type: "asset" or "industry".

        Returns:
            Dict with target product metadata and neighbor list.
        """
        fm = self.build_features(
            report_date=report_date,
            product_types=product_types,
            feature_type=feature_type,
        )
        use_raw = metric in ("overlap", "jaccard")
        neighbors = find_neighbors(
            fm, product_id, top_n=top_n, metric=metric, use_raw_weights=use_raw
        )

        target_idx = int(np.where(fm.product_ids == product_id)[0][0])
        return {
            "product_id": product_id,
            "product_code": str(fm.product_codes[target_idx]),
            "product_name": str(fm.product_names[target_idx]),
            "metric": metric,
            "feature_type": feature_type,
            "neighbors": neighbors,
        }

    def attribute_cluster(
        self,
        cluster_id: int,
        report_date: date | str,
        start_date: date | str,
        end_date: date | str,
        algorithm: str = "kmeans-asset",
        k: int | None = None,
        product_type_filter: str | None = None,
        benchmark: str = "cluster_avg",
        benchmark_code: str | None = None,
        save: bool = True,
    ) -> dict[str, Any]:
        """Run Brinson attribution for products in a cluster.

        Args:
            cluster_id: Target cluster id.
            report_date: Holding report date used as the weight snapshot.
            start_date: Attribution window start.
            end_date: Attribution window end.
            algorithm: Cluster algorithm identifier.
            k: Number of clusters.
            product_type_filter: Product type filter used for the run.
            benchmark: Benchmark type: ``cluster_avg`` or ``index``.
            benchmark_code: Index code when benchmark is ``index``
                (e.g. ``000300`` or ``000906``).
            save: Whether to persist results to the database.

        Returns:
            Dict with run metadata and attribution results.
        """
        if benchmark not in ("cluster_avg", "index"):
            raise ValueError(f"Unsupported benchmark: {benchmark}")
        if benchmark == "index" and not benchmark_code:
            raise ValueError("benchmark_code is required when benchmark='index'")

        run = load_cluster_run(
            report_date,
            algorithm=algorithm,
            k=k,
            product_type_filter=product_type_filter,
        )
        members = [
            m for m in run["members"] if m["cluster_id"] == cluster_id
        ]
        if not members:
            raise ValueError(
                f"No members found for cluster {cluster_id} in run {run['cluster_run_id']}"
            )

        if isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)
        if isinstance(end_date, str):
            end_date = date.fromisoformat(end_date)

        benchmark_holdings = None
        if benchmark == "index":
            index_df = load_index_weights(benchmark_code)
            benchmark_holdings = pd.DataFrame(
                {
                    "asset_code": index_df["constituent_code"],
                    "market": index_df["market"],
                    "weight": index_df["weight"],
                }
            )

        results = attribute_products(
            report_date=run["report_date"],
            start_date=start_date,
            end_date=end_date,
            members=members,
            benchmark_holdings=benchmark_holdings,
        )

        if save:
            save_attribution(
                cluster_run_id=run["cluster_run_id"],
                cluster_id=cluster_id,
                report_date=run["report_date"],
                start_date=start_date,
                end_date=end_date,
                benchmark_type=benchmark,
                benchmark_code=benchmark_code,
                results=results,
            )

        return {
            "cluster_run_id": run["cluster_run_id"],
            "cluster_id": cluster_id,
            "report_date": run["report_date"],
            "algorithm": run["algorithm"],
            "k": run["k"],
            "start_date": start_date,
            "end_date": end_date,
            "benchmark": benchmark,
            "benchmark_code": benchmark_code,
            "n_products": len(results),
            "results": [self._attribution_to_dict(r) for r in results],
        }

    def attribute_run(
        self,
        report_date: date | str,
        start_date: date | str,
        end_date: date | str,
        algorithm: str = "kmeans-asset",
        k: int | None = None,
        product_type_filter: str | None = None,
        benchmark: str = "cluster_avg",
        benchmark_code: str | None = None,
        save: bool = True,
    ) -> dict[str, Any]:
        """Run Brinson attribution for every cluster in a run.

        Returns:
            Dict with summary counts and per-cluster results.
        """
        run = load_cluster_run(
            report_date,
            algorithm=algorithm,
            k=k,
            product_type_filter=product_type_filter,
        )
        cluster_ids = sorted({m["cluster_id"] for m in run["members"]})
        per_cluster: list[dict[str, Any]] = []
        for cid in cluster_ids:
            per_cluster.append(
                self.attribute_cluster(
                    cluster_id=cid,
                    report_date=report_date,
                    start_date=start_date,
                    end_date=end_date,
                    algorithm=algorithm,
                    k=k,
                    product_type_filter=product_type_filter,
                    benchmark=benchmark,
                    benchmark_code=benchmark_code,
                    save=save,
                )
            )
        return {
            "cluster_run_id": run["cluster_run_id"],
            "report_date": run["report_date"],
            "algorithm": run["algorithm"],
            "k": run["k"],
            "benchmark": benchmark,
            "benchmark_code": benchmark_code,
            "clusters_attributed": len(per_cluster),
            "total_products": sum(c["n_products"] for c in per_cluster),
            "clusters": per_cluster,
        }

    @staticmethod
    def _attribution_to_dict(r: Any) -> dict[str, Any]:
        return {
            "product_id": r.product_id,
            "cluster_id": r.cluster_id,
            "total_return": r.total_return,
            "benchmark_return": r.benchmark_return,
            "excess_return": r.excess_return,
            "allocation_effect": r.allocation_effect,
            "selection_effect": r.selection_effect,
            "interaction_effect": r.interaction_effect,
            "rank_in_cluster": r.rank_in_cluster,
        }

    @staticmethod
    def _profile_to_dict(p: ClusterProfile) -> dict[str, Any]:
        return {
            "cluster_id": p.cluster_id,
            "size": p.size,
            "cluster_label": p.cluster_label,
            "top_holdings": p.top_holdings,
            "top_industries": p.top_industries,
            "avg_hhi": p.avg_hhi,
            "avg_overlap": p.avg_overlap,
            "avg_overlap_raw": p.avg_overlap_raw,
            "ac_share_dominance_ratio": p.ac_share_dominance_ratio,
            "institution_distribution": p.institution_distribution,
            "representative_products": p.representative_products,
            "representative_codes": p.representative_codes,
            "representative_names": p.representative_names,
        }
