# CODEBUDDY.md This file provides guidance to CodeBuddy when working with code in this repository.

FundSeeker collects wealth-management / public-fund product data (lists, NAV, holdings, market quotes), then performs portfolio-holding similarity clustering (K-Means) and Brinson attribution, surfacing results through a read-only Flask UI and independent CLIs designed for agent/cron scheduling.

## Commands

Run everything from the project root. The codebase is not installed as a package, so set `PYTHONPATH=src` on every invocation. Python 3.10+, PostgreSQL, and a venv with `requirements.txt` are required.

### Set up environment
```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```
Creates a virtualenv and installs SQLAlchemy, pandas, Flask, requests, etc. (see `requirements.txt`). Database is PostgreSQL; configure it before any `init-db`/`collect`/`similarity` command.

### Initialize the database
```bash
PYTHONPATH=src python scripts/fundseeker_cli.py init-db
```
Creates all tables via `Base.metadata.create_all` (`src/fundseeker/models/tables.py`). Idempotent. Connection string comes from `FUNDSEEKER_DATABASE_URL` env var or `src/fundseeker/models/database_local.py` (gitignored).

### Collect data
```bash
PYTHONPATH=src python scripts/fundseeker_cli.py collect --all
```
Runs all collectors (fund companies, bank WM, holdings, market quotes) and prints a summary report. Use `--funds`, `--bank-wm`, `--holdings`, `--market-quotes`, `--fund YFD`, `--bank SPD`, or `--report` (summary only). `--force` re-collects existing data.

### Run similarity pipeline
```bash
PYTHONPATH=src python scripts/fundseeker_similarity.py pipeline \
    --report-date 2026-03-31 --start-date 2026-04-01 --end-date today --mode auto
```
Official analysis entry (delegates to `similarity/cli_core.py`). Subcommands: `cluster`, `attribution`, `list`, `list-baselines`, `profile`, `neighbors`, `refresh-quotes`, `refresh-index-weights`, `refresh-industries`. Use `--skip-cluster`/`--skip-attribution` to run partial steps.

### Run the web UI
```bash
PYTHONPATH=src python scripts/run_web.py
```
Starts the read-only Flask app on `http://127.0.0.1:5001`. Pages under `/`, `/product/<id>`, `/holdings`, `/dashboard`, `/similarity/...`, `/market`; JSON mirrors under `/api/...`.

### Run tests
```bash
PYTHONPATH=src .venv/bin/pytest tests/ -q
```
Runs the pytest suite. Similarity tests build `FeatureMatrix` objects in memory (no DB). To run a single test file: `PYTHONPATH=src .venv/bin/pytest tests/test_similarity.py -q`.

## Architecture

### Layered pipeline
FundSeeker is a three-stage pipeline with PostgreSQL as the shared store:

1. **Collection layer** (`src/fundseeker/collectors/` + `runner.py`) scrapes external sites and writes normalized rows.
2. **Analysis layer** (`src/fundseeker/similarity/`) reads raw holdings and writes clustering/attribution results.
3. **Presentation layer** (`src/fundseeker/web/`) reads everything read-only.

The two CLIs (`scripts/fundseeker_cli.py`, `scripts/fundseeker_similarity.py`) and the web app are the only entry points; business logic lives in `runner.py` and `similarity/service.py`, not in the scripts.

### Data model (`src/fundseeker/models/tables.py`)
The schema is defined with SQLAlchemy 2.0 typed mapped columns on a single `Base`. Key relationships:

- `ProductInfo` is a **daily snapshot**, uniquely keyed by `(institution_code, product_code, collect_date)`. All time-series (NAV, returns, fees, holdings) reference a snapshot's `id`. When reading a logical product across days, join against the latest snapshot per `(institution_code, product_code)` — see `build_summary`'s `latest` CTE in `runner.py`.
- Holdings form a hierarchy: `HoldingReport` (one per product per quarter) → `ProductHolding`, `ProductAssetAllocation`, `ProductHoldingSummary`, with `HoldingSecurityInfo` as a reference table keyed by `(asset_code, market)`.
- Similarity results use a **run-centric** model: `SimilarityClusterRun` is the batch; `SimilarityCluster` / `SimilarityClusterMember` describe clusters and membership; `SimilarityClusterBaseline` stores centroids for incremental runs; `SimilarityAttribution` stores Brinson output; `IndexConstituentWeight` stores benchmark constituents.

All writers use PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` with explicit unique constraints, so re-runs are safe and idempotent. `CollectionLog` records every job for the summary report and failure diagnostics.

### Collection layer
`BaseCollector` (`collectors/base.py`) is the abstract interface: subclasses implement `collect_product_list()` and `normalize()` (raw → unified `product_info` schema). `runner.py` provides the high-level `run_fund_company` / `run_bank_wm` / `run_holdings` / `run_market_quotes` functions, each returning a `TaskResult` and writing a `CollectionLog`. Collectors are registered in dictionaries (`FUND_COLLECTORS`, `BANK_WM_COLLECTORS`) keyed by institution code; adding a source means writing a subclass and registering it.

Holdings use a separate `HoldingCollector` base (`collectors/holding_base.py`) with `collect_holdings()` returning a standardized dict. The main implementation is `EastmoneyFundHoldingCollector` (`collectors/eastmoney_holding.py`); fund-company product lists come from `FundCompanyCollector` (Eastmoney public API), while bank WM collectors (`*wm.py`) scrape official sites. All HTTP goes through `utils/http.py::PoliteHttpClient`, which applies per-institution rate limits and robots.txt rules from `config/institutions.yaml`.

Config is loaded by `src/fundseeker/config.py::load_config` from `config/institutions.yaml` (institution list, `sources`, `global` request policy, `risk_level_mapping`, `product_type_mapping`). Collectors read their `request` block from this config.

### Similarity analysis layer (`src/fundseeker/similarity/`)
`service.py::SimilarityService` is the stateless orchestrator (read-only w.r.t. raw tables; writes only to `similarity_*` tables). The computation flow:

1. `data.load_holdings` pulls a report-date cross-section into a `HoldingData`.
2. `features.build_weight_matrix` / `build_industry_matrix` produce a `FeatureMatrix` (products × assets/industries, optionally L2-normalized, optionally de-duplicating A/C share classes). `feature_type` is `"asset"` or `"industry"`; the algorithm id is `kmeans-asset` / `kmeans-industry`.
3. `clustering.kmeans` / `select_k_elbow` run K-Means (`k` fixed or `"auto"` via silhouette+elbow composite). `similarity.config.SimilarityConfig` (dataclass) holds `ClusterConfig` + `IncrementalConfig` defaults.
4. `profiling.build_profiles` derives cluster labels, top holdings/industries, HHI, overlap.
5. `persistence.save_cluster_run` writes run/cluster/member rows, replacing prior runs for the same `(report_date, algorithm, k, product_type_filter)` while preserving runs referenced as baselines.

**Incremental clustering** (v1.01): `cluster()` accepts `mode` `auto`/`full`/`incremental`. A full run persists a `SimilarityClusterBaseline` (centroids + feature names). An incremental run loads the baseline, `baseline.align_centroids` re-aligns features to the current feature space, and `kmeans_from_centroids` warm-starts. `baseline.should_fall_back_to_full` checks silhouette floor, silhouette-drop ratio, inertia change, product-count change, and feature Jaccard; on violation, `auto` mode transparently recomputes full, while explicit `incremental` raises. `list_baselines` and `refresh-quotes`/`refresh-index-weights` support this workflow.

**Attribution**: `attribution.attribute_products` computes Brinson allocation/selection/interaction effects per cluster member over a date window, benchmarked against `cluster_avg` or an index (`index_weights.load_index_weights`, codes like `000300`). `attribute_cluster` / `attribute_run` persist to `SimilarityAttribution`. `similarity.find_neighbors` supports overlap/cosine/jaccard neighbor lookup. `industry` maps securities to industries (from DB or Eastmoney); `quotes` backfills per-holding daily prices; `labels` derives human-readable cluster names.

### Web layer (`src/fundseeker/web/`)
`app.py` is a Flask app factory with read-only routes and JSON APIs; all SQL lives in `queries.py` (dataclass rows + `to_dict()`). Templates in `web/templates/`, static assets in `web/static/`. The app never mutates data — any write path is in the CLIs/cron scripts.

### Scheduling
`scripts/fundseeker_cron.sh` (daily collection) and `scripts/fundseeker_similarity_cron.sh` (analysis) are pure bash+python with zero LLM calls, designed for OpenClaw/cron. They honor holidays, apply timeouts, and emit a Feishu-style stdout payload. Never put business logic in these scripts; they should only invoke the CLIs.

### Conventions & gotchas
- Always invoke scripts with `PYTHONPATH=src` from the repo root; the scripts themselves add `src` to `sys.path`.
- `python -m fundseeker.similarity.cli` is **deprecated** — use `scripts/fundseeker_similarity.py`.
- DB connection: set `FUNDSEEKER_DATABASE_URL`, or create gitignored `src/fundseeker/models/database_local.py` defining `DEFAULT_DB_URL`. Do not commit real credentials.
- Similarity tests are DB-free (synthetic `FeatureMatrix`); collection/query tests may need a live DB.
- `.venv/`, `.claude/`, `.agents/`, `skills-lock.json` are gitignored local files — do not commit.
- `archive/` holds v1.0 history; `docs/` holds design/评审 docs; `Proposal/` holds data-source specs.
