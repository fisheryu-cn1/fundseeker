# FundSeeker 持仓相似性分析 CLI 使用说明

> 本文档说明 `scripts/fundseeker_similarity.py` 的使用方法。该 CLI 专门用于产品持仓相似性聚类、簇画像、Brinson 归因及相关数据准备，与信息采集 CLI（`scripts/fundseeker_cli.py`）和查询 CLI（`scripts/fundseeker_query.py`）相互独立，便于 agent 单独调度管理。

---

## 1. 设计定位

| CLI | 职责 | 典型调用方 |
|---|---|---|
| `scripts/fundseeker_cli.py` | 产品、净值、持仓、行情等数据采集 | 数据采集 agent / cron |
| `scripts/fundseeker_query.py` | 只读查询，输出 Markdown 报告 | 分析型 agent |
| `scripts/fundseeker_similarity.py` | 持仓相似性聚类、归因、行情补录 | 分析调度 agent / cron |

`fundseeker_similarity.py` 不直接参与原始数据采集，而是基于已入库的持仓、行情、指数权重等数据，执行聚类分析并持久化结果到 `similarity_*` 表。

---

## 2. 快速开始

### 2.1 环境要求

- Python 3.10+
- 已安装项目依赖（`requirements.txt`）
- PostgreSQL 数据库可连接（默认使用 `FUNDSEEKER_DATABASE_URL` 环境变量或本地 socket）

### 2.2 基本调用格式

```bash
PYTHONPATH=src python scripts/fundseeker_similarity.py <command> [options]
```

所有命令均输出 JSON 到 stdout，便于 agent 解析。

### 2.3 命令一览

```bash
PYTHONPATH=src python scripts/fundseeker_similarity.py --help
```

可用子命令：

| 子命令 | 说明 |
|---|---|
| `cluster` | 对指定报告期执行持仓聚类 |
| `attribution` | 对指定簇或全部簇执行 Brinson 归因 |
| `list` | 列出某报告期下的所有簇摘要 |
| `profile` | 查看指定簇的画像详情 |
| `neighbors` | 查找与指定产品最相似的产品 |
| `refresh-quotes` | 补录持仓涉及个股的日行情 |
| `refresh-index-weights` | 从中证官网采集指数成分股权重 |
| `refresh-industries` | 刷新持仓证券的行业映射 |
| `pipeline` | 执行完整分析流水线：指数权重 → 行情 → 聚类 → 归因 |

---

## 3. 命令详解

### 3.1 `cluster` — 执行聚类

对指定报告期的权益/混合类产品持仓进行聚类，默认基于个股权重向量（`feature-type=asset`）。

```bash
# 使用最新报告期，自动选择 k
PYTHONPATH=src python scripts/fundseeker_similarity.py cluster

# 指定报告期与聚类数
PYTHONPATH=src python scripts/fundseeker_similarity.py cluster \
    --report-date 2026-03-31 \
    --k 8

# 基于行业特征聚类
PYTHONPATH=src python scripts/fundseeker_similarity.py cluster \
    --report-date 2026-03-31 \
    --feature-type industry \
    --k auto
```

主要参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--report-date` | 数据库最新报告期 | 持仓报告期 `YYYY-MM-DD` |
| `--product-types` | `equity,mixed` | 参与聚类的产品类型 |
| `--k` | `auto` | 聚类数，可为整数或 `auto` |
| `--feature-type` | `asset` | 特征空间：`asset`（个股权重）/ `industry`（行业权重） |
| `--no-save` | — | 仅输出结果，不写入数据库 |

---

### 3.2 `attribution` — Brinson 归因

对簇内产品相对于簇平均持仓或指数基准进行 Brinson 归因。

```bash
# 对全部簇使用 cluster_avg 基准归因
PYTHONPATH=src python scripts/fundseeker_similarity.py attribution \
    --report-date 2026-03-31 \
    --all-clusters \
    --start-date 2026-04-01 \
    --end-date 2026-07-10

# 对单个簇使用沪深300指数基准归因
PYTHONPATH=src python scripts/fundseeker_similarity.py attribution \
    --report-date 2026-03-31 \
    --cluster-id 0 \
    --start-date 2026-04-01 \
    --end-date 2026-07-10 \
    --benchmark index \
    --benchmark-code 000300
```

主要参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--report-date` | 数据库最新报告期 | 持仓报告期 |
| `--cluster-id` | — | 簇编号（与 `--all-clusters` 二选一） |
| `--all-clusters` | — | 对该运行下的所有簇执行归因 |
| `--start-date` | 必填 | 归因起始日，可填 `today` |
| `--end-date` | 必填 | 归因截止日，可填 `today` |
| `--algorithm` | `kmeans-asset` | 聚类算法标识 |
| `--k` | — | 聚类数 k |
| `--benchmark` | `cluster_avg` | 基准类型：`cluster_avg` / `index` |
| `--benchmark-code` | — | 指数代码，`benchmark=index` 时必填 |
| `--no-save` | — | 仅输出，不写入数据库 |

---

### 3.3 `list` — 列出簇摘要

```bash
PYTHONPATH=src python scripts/fundseeker_similarity.py list \
    --report-date 2026-03-31 \
    --algorithm kmeans-asset
```

输出包含每个簇的规模、平均 overlap、Top 行业、Top 持仓、代表产品代码等。

---

### 3.4 `profile` — 查看簇画像

```bash
PYTHONPATH=src python scripts/fundseeker_similarity.py profile \
    --report-date 2026-03-31 \
    --cluster-id 0
```

---

### 3.5 `neighbors` — 相似产品查询

```bash
PYTHONPATH=src python scripts/fundseeker_similarity.py neighbors \
    --product-id 117661 \
    --report-date 2026-03-31 \
    --top-n 10 \
    --metric overlap
```

可选 `--metric`：`overlap` / `cosine` / `jaccard`。

---

### 3.6 `refresh-quotes` — 补录行情

为指定报告期持仓涉及的股票补录日行情，供归因计算使用。

```bash
# 补录从报告期到今日的全部行情
PYTHONPATH=src python scripts/fundseeker_similarity.py refresh-quotes \
    --report-date 2026-03-31

# 指定区间
PYTHONPATH=src python scripts/fundseeker_similarity.py refresh-quotes \
    --report-date 2026-03-31 \
    --start-date 2026-04-01 \
    --end-date 2026-07-10

# 仅统计需补录数量
PYTHONPATH=src python scripts/fundseeker_similarity.py refresh-quotes \
    --report-date 2026-03-31 --dry-run
```

---

### 3.7 `refresh-index-weights` — 刷新指数权重

从中证官网采集指数成分股权重，默认沪深300 + 中证800。

```bash
PYTHONPATH=src python scripts/fundseeker_similarity.py refresh-index-weights

# 指定指数
PYTHONPATH=src python scripts/fundseeker_similarity.py refresh-index-weights \
    --index-codes 000300,000906
```

---

### 3.8 `refresh-industries` — 刷新行业映射

从东方财富等来源更新 `holding_security_info` 中的行业信息。

```bash
PYTHONPATH=src python scripts/fundseeker_similarity.py refresh-industries

# 仅统计
PYTHONPATH=src python scripts/fundseeker_similarity.py refresh-industries --dry-run
```

---

### 3.9 `pipeline` — 完整分析流水线

一次性执行：指数权重刷新 → 行情补录 → 聚类 → 归因。适合季度持仓披露后或每日收盘后由 agent 调用。

```bash
# 季度完整跑批
PYTHONPATH=src python scripts/fundseeker_similarity.py pipeline \
    --report-date 2026-03-31 \
    --start-date 2026-04-01 \
    --end-date 2026-07-10

# 每日增量：仅补行情 + 用已有聚类重新归因
PYTHONPATH=src python scripts/fundseeker_similarity.py pipeline \
    --report-date 2026-03-31 \
    --start-date 2026-04-01 \
    --end-date today \
    --skip-cluster \
    --skip-index-weights

# 使用指数基准归因
PYTHONPATH=src python scripts/fundseeker_similarity.py pipeline \
    --report-date 2026-03-31 \
    --start-date 2026-04-01 \
    --end-date 2026-07-10 \
    --benchmark index \
    --benchmark-code 000300
```

`pipeline` 支持以下跳过参数：

| 参数 | 说明 |
|---|---|
| `--skip-index-weights` | 跳过指数权重刷新 |
| `--skip-quotes` | 跳过行情补录 |
| `--skip-cluster` | 跳过聚类，使用已有运行 |
| `--skip-attribution` | 跳过归因 |

---

## 4. 推荐调度策略

### 4.1 季度调度（持仓披露后）

每季度基金/银行理财持仓披露后执行一次完整流水线：

```bash
PYTHONPATH=src python scripts/fundseeker_similarity.py pipeline \
    --start-date 2026-04-01 \
    --end-date today \
    --benchmark index \
    --benchmark-code 000300
```

`--report-date` 自动取最新报告期。

### 4.2 每日调度（行情更新后）

每日收盘行情入库后，基于最新行情更新归因：

```bash
PYTHONPATH=src python scripts/fundseeker_similarity.py pipeline \
    --start-date 2026-04-01 \
    --end-date today \
    --skip-cluster \
    --skip-index-weights
```

### 4.3 月度调度（指数权重更新）

指数成分股权重通常按月调整，可每月初刷新：

```bash
PYTHONPATH=src python scripts/fundseeker_similarity.py refresh-index-weights
```

---

## 5. 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 执行成功 |
| `1` | 执行过程中发生异常 |
| `2` | 命令行参数错误 |

---

## 6. 输出说明

- 所有命令默认输出 JSON。
- 成功时可直接被下游 agent 解析。
- 错误信息输出到 stderr。

---

## 7. 注意事项

1. **`--report-date` 自动取值**：未指定时，CLI 会从 `product_holding.report_date` 取最大值。若数据库为空会报错。
2. **归因日期格式**：`--start-date` / `--end-date` 支持 `YYYY-MM-DD` 或 `today`。
3. **幂等性**：
   - `refresh-index-weights`、`refresh-quotes` 对重复数据通常会跳过或覆盖。
   - `cluster` 每次运行都会新增一条 `similarity_cluster_run` 记录。
   - `attribution` 受唯一约束 `(product_id, cluster_run_id, start_date, end_date, benchmark_type, benchmark_code)` 保护，重复执行会覆盖同维度记录。
4. **资源消耗**：`cluster` 和 `attribution --all-clusters` 涉及全量持仓计算，建议在非交易高峰时段运行。
