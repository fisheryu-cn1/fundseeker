# FundSeeker OpenClaw 定时调度指南（v1.01）

> 版本：v1.01  
> 说明：本文档在 v1.0 采集调度指南基础上，新增持仓相似性分析（聚类/归因）的定时调度建议及 `scripts/fundseeker_similarity_cron.sh` 使用方式。v1.0 版本保留在 `docs/ver1.0/openclaw-scheduling-guide-v1.0.md`。

---

## 1. 概述

FundSeeker 提供两类命令行入口，分别对应「数据采集」和「持仓相似性分析」两大独立服务：

| 入口 | 职责 | 对应 cron 脚本 |
|---|---|---|
| `scripts/fundseeker_cli.py` | 产品、净值、持仓、行情等数据采集 | `scripts/fundseeker_cron.sh` |
| `scripts/fundseeker_similarity.py` | 持仓聚类、归因、行情补录、指数权重刷新 | `scripts/fundseeker_similarity_cron.sh` |

每次执行完成后，程序在 stdout 打印结构化汇总报告，供 Agent 判断是否需要进行后续处理。

---

## 2. 前置要求

1. **工作目录**: `/home/cc/projects/fundseeker`
2. **Python 环境**: 项目虚拟环境 `.venv`
3. **数据库**: PostgreSQL 已启动，数据库 `fundseeker` 可连接
4. **依赖**: 已通过 `pip install -r requirements.txt` 安装

---

## 3. 数据采集入口（与 v1.0 一致）

统一入口：

```bash
cd /home/cc/projects/fundseeker
source .venv/bin/activate
PYTHONPATH=src python scripts/fundseeker_cli.py <command> [options]
```

### 3.1 常用采集命令

| 命令 | 说明 |
|---|---|
| `init-db` | 初始化数据库表 |
| `report` | 只读状态报告 |
| `collect --all` | 全量采集 |
| `collect --funds` | 仅基金公司与净值 |
| `collect --bank-wm` | 仅银行理财子与净值 |
| `collect --holdings` | 仅持仓数据 |
| `collect --market-quotes` | 市场行情 |

退出码：

| 退出码 | 含义 |
|--------|------|
| 0 | 所有任务成功完成（`skipped` 不算失败） |
| 1 | 至少有一个采集任务失败 |
| 2 | 命令行参数错误 |

详细说明参见 `docs/ver1.0/openclaw-scheduling-guide-v1.0.md`。

---

## 4. 相似性分析入口（v1.01 新增/更新）

官方入口：

```bash
cd /home/cc/projects/fundseeker
source .venv/bin/activate
PYTHONPATH=src python scripts/fundseeker_similarity.py <command> [options]
```

### 4.1 专用 cron 脚本

`scripts/fundseeker_similarity_cron.sh` 封装了 `pipeline` 跑批，通过环境变量控制行为：

```bash
# 每日自动增量跑批
SIMILARITY_MODE=auto \
SKIP_INDEX_WEIGHTS=1 \
  bash scripts/fundseeker_similarity_cron.sh

# 季度全量跑批
SIMILARITY_MODE=full \
SIMILARITY_K=auto \
SIMILARITY_BENCHMARK=index \
SIMILARITY_BENCHMARK_CODE=000300 \
  bash scripts/fundseeker_similarity_cron.sh
```

环境变量说明：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `SIMILARITY_MODE` | `auto` | 聚类模式：`full` / `auto` / `incremental` |
| `SIMILARITY_REPORT_DATE` | 数据库最新报告期 | 持仓报告期 |
| `SIMILARITY_START_DATE` | `report_date`（未设置时兜底 `today`） | 归因起始日 |
| `SIMILARITY_END_DATE` | `today` | 归因截止日 |
| `SIMILARITY_FEATURE_TYPE` | `asset` | 特征空间：`asset` / `industry` |
| `SIMILARITY_K` | `auto` | 聚类数或 `auto` |
| `SIMILARITY_BENCHMARK` | `cluster_avg` | 归因基准 |
| `SIMILARITY_BENCHMARK_CODE` | — | 指数代码，`benchmark=index` 时必填 |
| `SKIP_INDEX_WEIGHTS` | `0` | `1` 时跳过指数权重刷新 |
| `SKIP_QUOTES` | `0` | `1` 时跳过行情补录 |

退出码：

| 退出码 | 含义 |
|--------|------|
| 0 | 执行成功 |
| 1 | 任务执行失败但报告已输出到 stdout |
| >=2 | 脚本或参数错误 |

---

## 5. OpenClaw 定时任务配置建议

### 5.1 数据采集任务（与 v1.0 一致）

| 任务 | 频率 | 建议命令 | 说明 |
|------|------|----------|------|
| 全量采集 | 每日一次 | `collect --all` | 抓取所有机构最新产品和净值、市场行情，并补充持仓 |
| 产品/净值补采 | 每 6 小时 | `collect --funds` 和 `collect --bank-wm` | 对失败机构重试 |
| 市场行情补采 | 每日一次（收盘后） | `collect --market-quotes` | 每个交易日收盘后补充当日行情 |
| 持仓补采 | 每周一次 | `collect --holdings` | 季度持仓披露不频繁，每周增量补充即可 |
| 数据巡检 | 每小时 | `report` | 只读查询，输出当前状态 |

### 5.2 相似性分析任务（v1.01 新增）

| 任务 | 频率 | 建议命令 | 说明 |
|------|------|----------|------|
| 相似性每日跑批 | 每日 19:00 | `pipeline --mode auto --skip-index-weights` | 行情更新后自动增量聚类+归因；无基线或质量劣化时自动回退全量 |
| 相似性季度跑批 | 持仓披露后 | `pipeline --mode full --k auto` | 全量重算并更新基线 |
| 指数权重刷新 | 每月第一个交易日 09:30 | `refresh-index-weights` | 更新沪深300/中证800成分股权重 |

### 5.3 OpenClaw 配置示例

#### 每日相似性跑批

```yaml
jobs:
  fundseeker_similarity_daily:
    schedule: "0 19 * * *"
    command: |
      cd /home/cc/projects/fundseeker &&
      source .venv/bin/activate &&
      SIMILARITY_MODE=auto SKIP_INDEX_WEIGHTS=1 bash scripts/fundseeker_similarity_cron.sh
    timeout: 1800
    on_failure: notify
```

> `SIMILARITY_START_DATE` 未设置时，cron 脚本会默认使用 `SIMILARITY_REPORT_DATE`；若报告期也未设置，则兜底为 `today`。

#### 季度全量跑批

```yaml
jobs:
  fundseeker_similarity_quarterly:
    schedule: "0 9 1 1,4,7,10 *"  # 季度首日 09:00，实际应根据披露时间手动触发或调整
    command: |
      cd /home/cc/projects/fundseeker &&
      source .venv/bin/activate &&
      SIMILARITY_MODE=full SIMILARITY_K=auto SIMILARITY_BENCHMARK=index SIMILARITY_BENCHMARK_CODE=000300 bash scripts/fundseeker_similarity_cron.sh
    timeout: 3600
    on_failure: notify
```

#### 每月指数权重刷新

```yaml
jobs:
  fundseeker_similarity_index_weights:
    schedule: "30 9 1 * *"
    command: |
      cd /home/cc/projects/fundseeker &&
      source .venv/bin/activate &&
      PYTHONPATH=src python scripts/fundseeker_similarity.py refresh-index-weights
    timeout: 600
    on_failure: notify
```

---

## 6. Agent 判断后续工作的规则

### 6.1 采集任务（与 v1.0 一致）

1. **如果退出码为 1**：
   - 查看"本次执行任务"中失败的任务。
   - 如果是网络/临时错误，建议 30 分钟后重试对应子命令。
   - 如果是结构性错误（如 WAF、验证码、接口变更），记录到 issue 并转人工处理。

2. **如果"有净值产品"覆盖率低于 80%**：
   - 优先重试 `--funds` 和 `--bank-wm`。
   - 对长期失败的机构，考虑切换数据源或人工介入。

3. **如果"有持仓产品"覆盖率低于预期**：
   - 执行 `collect --holdings` 增量补充。
   - 对银行理财子产品，评估是否需要接入中国理财网或 PDF 解析。

### 6.2 相似性分析任务（v1.01 新增）

1. **首次部署或无基线时**：
   - 执行 `list-baselines` 确认是否已有基线。
   - 若无基线，必须执行一次 `pipeline --mode full --k auto` 或 `cluster --mode full --k auto`。

2. **每日跑批后检查 `pipeline` 输出**：
   - 若 `cluster.mode == "full"` 且不是季度跑批，说明 `auto` 模式因质量劣化触发回退。
   - 若连续多次触发回退，建议人工复核后执行 `--mode full` 并重新评估 K 值。

3. ** silhouette 持续下降时**：
   - 查看 `cluster.incremental_diagnostics.checks.silhouette_drop_ratio`。
   - 若下降比例超过配置阈值（默认见 `SimilarityConfig`），建议执行 `--mode full`。

4. **节假日处理**：
   - 相似性分析的行情补录依赖交易日数据，节假日可跳过 `refresh-quotes` 和归因任务。
   - 指数权重刷新不受节假日影响，可按月执行。

---

## 7. 注意事项

1. **采集与分析分离**：
   - `fundseeker_cron.sh` 只负责数据采集；
   - `fundseeker_similarity_cron.sh` 只负责相似性分析；
   - 两者不要合并，便于独立监控、独立超时控制。

2. **并发风险**：
   - 不要同时启动多个 `collect --holdings` 实例；
   - 不要同时启动多个 `pipeline --mode full` 实例，避免基线表竞争。

3. **超时设置**：
   - 每日 `auto` 模式建议 1800s；
   - 季度 `full` 模式建议 3600s；
   - 指数权重刷新建议 600s。

4. **日志详情**：
   - 标准输出报告是摘要；
   - 完整错误信息写入 `collection_log.error_message` 或聚类运行记录的 `params_json`；
   - 可连接数据库查询。

5. **旧入口兼容**：
   - `python -m fundseeker.similarity.cli` 已标记 deprecated，会打印警告；
   - 新 cron 和 OpenClaw 任务请使用 `scripts/fundseeker_similarity.py`。

---

## 8. 常用调试命令

```bash
# 检查基线
cd /home/cc/projects/fundseeker
source .venv/bin/activate
PYTHONPATH=src python scripts/fundseeker_similarity.py list-baselines

# 测试单次全量聚类
PYTHONPATH=src python scripts/fundseeker_similarity.py cluster \
    --report-date 2026-03-31 --mode full --k auto --no-save

# 测试每日增量流水线
PYTHONPATH=src python scripts/fundseeker_similarity.py pipeline \
    --start-date 2026-04-01 --end-date today \
    --mode auto --skip-index-weights --skip-attribution

# 测试相似性 cron（不写入）
SIMILARITY_MODE=auto \
SKIP_INDEX_WEIGHTS=1 \
SKIP_QUOTES=1 \
  bash scripts/fundseeker_similarity_cron.sh
```
