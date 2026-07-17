# Fundseeker v1.0 Archive

存档时间：2026-07-15

本目录保存 1.0 版本的设计方案文档与核心代码快照，作为后续 1.01 增量聚类优化版本的基线。

## 目录结构

- `design_docs/`：1.0 版设计、评审与说明文档
- `code/similarity/`：持仓相似性分析模块源码
- `code/web/`：Flask Web UI 源码
- `tests/`：Web 层测试
- `reports/`：已生成的行业相关性分析报告

## 1.0 版关键特征

- 聚类方式：每次执行均为全量 K-Means 计算，不保留历史质心。
- K 值选择：`--k auto` 时基于 silhouette 在 `[k_min, k_max]` 范围内搜索；指定整数时按该 k 执行。
- 输出产物：每次运行生成新的 `similarity_cluster_run` 记录，历史运行保留。
- 监控指标：仅展示 silhouette / inertia，未建立有效性劣化判断与全量/增量切换机制。
