#!/usr/bin/env python3
"""独立 CLI：产品持仓相似性分析与聚类处理。

本脚本与信息采集 CLI（scripts/fundseeker_cli.py）和查询 CLI
（scripts/fundseeker_query.py）分离，专门供 agent 定期调度执行聚类、
归因、行情补录等分析任务。

实现已迁移至 ``fundseeker.similarity.cli_core``；本文件仅作为官方入口，
保持与旧版文档和 cron 脚本的兼容性。

典型调度场景：

    # 季度持仓披露后，执行完整分析流水线
    PYTHONPATH=src python scripts/fundseeker_similarity.py pipeline \
        --report-date 2026-03-31 --start-date 2026-04-01 --end-date 2026-07-10

    # 每日收盘后，仅补录行情并更新归因
    PYTHONPATH=src python scripts/fundseeker_similarity.py pipeline \
        --report-date 2026-03-31 --start-date 2026-04-01 --end-date today \
        --skip-cluster --benchmark index --benchmark-code 000300

    # 单独执行聚类（report-date 默认取最新报告期）
    PYTHONPATH=src python scripts/fundseeker_similarity.py cluster

    # 对全部簇执行 Brinson 归因
    PYTHONPATH=src python scripts/fundseeker_similarity.py attribution \
        --all-clusters --start-date 2026-04-01 --end-date 2026-07-10

    # 刷新指数成分股权重（沪深300 + 中证800）
    PYTHONPATH=src python scripts/fundseeker_similarity.py refresh-index-weights
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from fundseeker.similarity.cli_core import main

if __name__ == "__main__":
    sys.exit(main())
