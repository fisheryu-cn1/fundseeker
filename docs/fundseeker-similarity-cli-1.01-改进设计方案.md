# FundSeeker 持仓相似性 CLI 1.01 改进设计方案

> 版本：1.01  
> 目标：配合 v1.01 增量/全量聚类能力，升级 CLI 设计与使用文档，使其更便于 agent / cron 定期调度，并减少双入口维护成本。

---

## 1. 现状评估

### 1.1 已具备的 v1.01 能力

v1.01 增量聚类方案已在 `scripts/fundseeker_similarity.py` 中落地：

- `cluster` 与 `pipeline` 子命令新增 `--mode {auto,full,incremental}`：
  - `auto`：有基线则尝试增量，无基线或指标劣化时自动回退全量；
  - `full`：始终执行全量并更新基线；
  - `incremental`：要求已有基线，否则报错。
- 服务层 `SimilarityService.cluster` 已支持通过 `SimilarityClusterBaseline` 复用质心、监控 silhouette / inertia 等指标。

### 1.2 当前 CLI 设计问题

| 问题 | 影响 | 建议处理 |
|------|------|----------|
| 存在两个重叠入口：`src/fundseeker/similarity/cli.py` 与 `scripts/fundseeker_similarity.py` | 维护两份参数解析和命令逻辑；模板/查询脚本仍引用旧入口 | v1.01 统一为单一入口，旧入口标记 deprecated 并做兼容转发 |
| 缺少基线管理命令 | agent 无法直接判断能否执行 incremental，必须查数据库 | 新增 `list-baselines` 子命令 |
| `--mode` 参数未在使用说明文档中体现 | 用户/ agent 不了解增量调度方式 | 新增 v1.01 版 CLI 使用说明 |
| 缺少相似性分析专用 cron 脚本 | 每日/季度跑批需手工拼接命令 | 新增 `scripts/fundseeker_similarity_cron.sh` |
| OpenClaw 调度指南未覆盖相似性分析 | 采集与分析任务混在一起，无独立调度建议 | 新增 v1.01 版调度指南 |

**结论**：需要同步升级 CLI 设计及相关文档。

---

## 2. 设计目标

1. **单一入口**：以 `scripts/fundseeker_similarity.py` 为官方 CLI；`src/fundseeker/similarity/cli.py` 变为兼容转发层。
2. **基线可见**：提供 `list-baselines` 命令，让 agent 在调用前确认基线状态。
3. **调度友好**：提供专用 cron 脚本和 OpenClaw 配置示例，区分季度全量、每日增量两种场景。
4. **文档对齐**：新增 v1.01 版使用说明和调度指南，旧 v1.0 文档保留在 `docs/ver1.0/`。

---

## 3. 具体改进项

### 3.1 CLI 入口统一

- 将 `scripts/fundseeker_similarity.py` 中的参数解析与命令实现抽取到 `src/fundseeker/similarity/cli_core.py`。
- `scripts/fundseeker_similarity.py` 变为 `from fundseeker.similarity.cli_core import main; sys.exit(main())`。
- `src/fundseeker/similarity/cli.py` 保留旧调用方式，但在 `main()` 入口打印 deprecation warning，并委托给 `cli_core.main()`：

  ```python
  warnings.warn(
      "python -m fundseeker.similarity.cli is deprecated, "
      "use PYTHONPATH=src python scripts/fundseeker_similarity.py instead.",
      DeprecationWarning,
      stacklevel=2,
  )
  ```

- 更新 `scripts/fundseeker_query.py` 和 `src/fundseeker/web/templates/similarity_index.html` 中的 CLI 入口示例字符串，改为 `scripts/fundseeker_similarity.py`。

### 3.2 新增 `list-baselines` 子命令

```bash
PYTHONPATH=src python scripts/fundseeker_similarity.py list-baselines \
    [--report-date YYYY-MM-DD] \
    [--algorithm ALGO] \
    [--feature-type asset|industry]
```

输出 JSON 字段：

| 字段 | 说明 |
|------|------|
| `baseline_id` | 基线记录 ID |
| `cluster_run_id` | 基线对应的聚类运行 ID |
| `report_date` | 基准报告期 |
| `product_type_filter` | 产品类型过滤条件 |
| `algorithm` | 算法标识，如 `kmeans-asset` |
| `feature_type` | `asset` / `industry` |
| `k` | 基线 K 值 |
| `silhouette` | 基线 silhouette 得分 |
| `inertia` | 基线 inertia |
| `n_products` | 参与产品数 |
| `k_search_results` | K 搜索历史（仅 `full` 且 `k=auto` 的基线有值） |
| `created_at` | 基线创建时间 |

服务层新增 `SimilarityService.list_baselines(...)` 方法，直接查询 `SimilarityClusterBaseline` 表。

### 3.3 `cluster` / `pipeline` 的 `--mode` 说明增强

在 help 文本和文档中明确三种模式的适用场景：

| 字段 | 说明 | 出现模式 |
|------|------|----------|
| `cluster_run_id` | 本次聚类运行 ID | 全模式 |
| `report_date` | 实际报告期 | 全模式 |
| `algorithm` | 算法标识，如 `kmeans-asset` | 全模式 |
| `k` | 实际使用的聚类数 | 全模式 |
| `feature_type` | `asset` / `industry` | 全模式 |
| `n_products` | 参与产品数 | 全模式 |
| `n_features` | 特征维度数 | 全模式 |
| `silhouette` | 本次 silhouette 得分 | 全模式 |
| `inertia` | 本次 SSE | 全模式 |
| `n_iter` | K-Means 收敛迭代数 | 全模式 |
| `mode` | 实际执行模式：`full` / `incremental` | 全模式 |
| `baseline_run_id` | 增量时所依赖的基线运行 ID | `auto` / `incremental`（非 `full`） |
| `k_search_results` | K 搜索结果 | `full` 且 `k=auto` |
| `incremental_diagnostics` | 增量质量检查明细 | `auto` / `incremental` |
| `profiles` | 各簇画像详情 | 全模式 |

### 3.4 新增 `scripts/fundseeker_similarity_cron.sh`

职责：与 `scripts/fundseeker_cron.sh` 分离，专门负责相似性分析跑批。

调度模式：

| 触发条件 | 命令 | 说明 |
|----------|------|------|
| 季度持仓披露后 | `pipeline --mode full --k auto` | 全量重算并更新基线 |
| 每日收盘后 | `pipeline --mode auto --skip-index-weights` | 行情更新后增量聚类+归因 |
| 月度 | `refresh-index-weights` | 更新指数成分股权重 |

脚本内部通过 `SIMILARITY_MODE` 环境变量控制行为：`SIMILARITY_START_DATE` 未设置时默认使用 `SIMILARITY_REPORT_DATE`，若报告期也未设置则兜底为 `today`。stdout 输出 JSON 摘要供 cron / agent 消费。

### 3.5 OpenClaw 调度指南 v1.01

新增 `docs/openclaw-scheduling-guide-v1.01.md`，在原有采集任务基础上增加：

- `fundseeker_similarity_daily`：每日 19:00 执行 `pipeline --mode auto --skip-index-weights`；
- `fundseeker_similarity_quarterly`：季度持仓披露后手动/定时触发 `pipeline --mode full --k auto`；
- `fundseeker_similarity_index_weights`：每月第一个交易日 09:30 执行 `refresh-index-weights`。

并给出 agent 判断规则：

1. 若 `list-baselines` 为空，则首次必须执行 `--mode full`；
2. 若上次 `auto` 运行触发了 fallback 且 silhouette 下降超过阈值，建议人工复核后执行 `--mode full`；
3. 节假日跳过相似性行情相关任务。

---

## 4. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/fundseeker/similarity/cli_core.py` | 新增 | 统一 CLI 解析与命令实现 |
| `src/fundseeker/similarity/service.py` | 修改 | 新增 `list_baselines` 方法 |
| `src/fundseeker/similarity/cli.py` | 修改 | 标记 deprecated，转发到 `cli_core` |
| `scripts/fundseeker_similarity.py` | 修改 | 委托给 `cli_core.main()` |
| `scripts/fundseeker_similarity_cron.sh` | 新增 | 相似性分析 cron 脚本 |
| `scripts/fundseeker_query.py` | 修改 | 更新 docstring 中的 CLI 入口示例字符串为脚本 CLI |
| `src/fundseeker/web/templates/similarity_index.html` | 修改 | 更新页面提示中的 CLI 入口示例字符串为脚本 CLI |
| `docs/fundseeker-similarity-cli-v1.01.md` | 新增 | v1.01 使用说明 |
| `docs/openclaw-scheduling-guide-v1.01.md` | 新增 | v1.01 调度指南 |
| `docs/fundseeker-similarity-cli-1.01-改进设计方案.md` | 新增 | 本设计文档 |

---

## 5. 兼容性

- `python -m fundseeker.similarity.cli` 继续可用，但打印 deprecation warning；
- `scripts/fundseeker_similarity.py` 的所有现有参数保持不变；
- `--mode` 默认值仍为 `auto`，不破坏现有调用；
- 新增的 `list-baselines` 为纯新增命令，不影响旧命令。

---

## 6. 验证计划

1. 运行 `PYTHONPATH=src python scripts/fundseeker_similarity.py --help` 和所有子命令 help，确认参数一致。
2. 运行 `PYTHONPATH=src python -m fundseeker.similarity.cli --help`，确认有 deprecation warning 且行为一致。
3. 运行 `list-baselines` 命令，确认 JSON 输出字段正确。
4. 运行 `cluster --mode auto|full|incremental --no-save`，确认模式选择生效。
5. 运行 cron 脚本（dry-run 或本地测试模式），确认输出摘要格式正确。
6. 执行 `PYTHONPATH=src .venv/bin/pytest tests/ -q`，确保 24 个用例全部通过。
