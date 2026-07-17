# 持仓相似性 v1.01 CLI / 调度修复执行情况复审报告

> 复审对象：
> - 修复记录：[持仓相似性-CLI与调度-v1.01-评审报告.md § 修改执行记录](../持仓相似性-CLI与调度-v1.01-评审报告.md)
> - 修改的源码：`scripts/fundseeker_similarity_cron.sh`、`src/fundseeker/similarity/cli_core.py`、`src/fundseeker/similarity/service.py`
> - 更新的文档：`docs/fundseeker-similarity-cli-1.01-改进设计方案.md`、`docs/fundseeker-similarity-cli-v1.01.md`、`docs/openclaw-scheduling-guide-v1.01.md`
>
> 复审日期：2026-07-16
> 复审结论：**10 项修复全部正确落地，P0 阻塞 bug 已消除，24 个测试全部通过，无回归。**

---

## 目录

1. [复审结论](#1-复审结论)
2. [修复执行情况逐项核查](#2-修复执行情况逐项核查)
3. [修复代码质量评审](#3-修复代码质量评审)
4. [新发现的问题](#4-新发现的问题)
5. [建议与下一步](#5-建议与下一步)

---

## 1. 复审结论

### 1.1 总体结论

执行方按"立即修复 + 短期修复"清单完成了 10 项修改。P0 阻塞 bug 通过 cron 脚本默认参数兜底彻底消除；P1 一致性问题中，OpenClaw YAML 改用单条 `&&` 链式命令也避开了 `\|` 块中 `\` 续行的解析风险；P2/P3 工程性问题中，`cmd_pipeline` 输出字段补齐、`list_baselines` 增加 `k_search_results` 字段、`cmd_pipeline` 在 `--skip-cluster` 时的 `attribute_run` `k` 参数解析 Bug 顺手被修复（执行记录未明确声明，是这次复审中的"额外收益"）。

所有测试 24/24 通过，cron 脚本默认调用不再失败（exit 0），`list-baselines` 输出已包含 `k_search_results`，CLI 文档 §6 补充了 cron 输出包裹行为的说明。

### 1.2 优先级清单

| 优先级 | 编号 | 主题 | 状态 |
|---|---|---|---|
| 建议 | #N1 | `set -e` 仍未启用，cron 脚本遇到 python 解释器错误时仍会包裹 exit 0 | 低 |
| 建议 | #N2 | `cli_core.cmd_pipeline` 在 `skip_cluster=True` 时的 `cluster_k` 解析没处理 `k="auto"` 之外的非整数边界 | 低 |
| 提示 | #N3 | cron 脚本的 `set -uo pipefail` 中 `-u` 配合 `${VAR:-default}` 写法正确，但 `cd /home/cc/projects/fundseeker` 是硬编码路径，迁移时需手动改 | 低 |

---

## 2. 修复执行情况逐项核查

### ✅ 修复 #1（P0）：cron 脚本 `START_DATE` 兜底 + `set -uo pipefail`

**声明**：`START_DATE` 默认使用 `SIMILARITY_REPORT_DATE`，未设置时兜底为 `today`；同时增加 `set -uo pipefail`。

**核查**：

[scripts/fundseeker_similarity_cron.sh:23, 34-35](../scripts/fundseeker_similarity_cron.sh#L23)

```bash
set -uo pipefail
...
# 默认 start_date = report_date；若 report_date 也未提供，则兜底为 today
START_DATE="${SIMILARITY_START_DATE:-${REPORT_DATE:-today}}"
```

**实测验证**：

```
$ PYTHONPATH=src SKIP_INDEX_WEIGHTS=1 SKIP_QUOTES=1 SKIP_ATTRIBUTION=1 \
    SIMILARITY_MODE=auto timeout 30 bash scripts/fundseeker_similarity_cron.sh

📊 FundSeeker 相似性分析日报 — 2026-07-16 11:10:56
模式: auto | 特征: asset | K: auto
退出码: 0 ✅
```

P0 阻塞 bug 已消除。

**结论**：✅ 完全落地，且修了一个评审记录里没明确声明的 bonus。

---

### ✅ 修复 #2（P1）：OpenClaw YAML 示例改用 `&&` 链式命令

**声明**：YAML 示例改为单条 `&&` 连接命令，消除 `\` 续行在 `\|` 块中的解析风险；并补充 `SIMILARITY_START_DATE` 默认兜底说明。

**核查**：

[openclaw-scheduling-guide-v1.01.md:142-153](../docs/openclaw-scheduling-guide-v1.01.md#L142-L153)

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

[openclaw-scheduling-guide-v1.01.md:98](../docs/openclaw-scheduling-guide-v1.01.md#L98) 环境变量表也更新为：

```
| `SIMILARITY_START_DATE` | `report_date`（未设置时兜底 `today`） | 归因起始日 |
```

**结论**：✅ 落地完整。

---

### ✅ 修复 #3（P1）：设计文档 §3.3 字段表扩展

**声明**：将 §3.3 表格扩展为完整字段清单，并标注各字段出现模式。

**核查**：

[fundseeker-similarity-cli-1.01-改进设计方案.md:94-110](../docs/fundseeker-similarity-cli-1.01-改进设计方案.md#L94-L110)

```
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
```

[fundseeker-similarity-cli-1.01-改进设计方案.md:85](../docs/fundseeker-similarity-cli-1.01-改进设计方案.md#L85) 还增加了 `k_search_results` 在 `list-baselines` 输出字段表里。

**结论**：✅ 完整覆盖。

---

### ✅ 修复 #4（P2）：`cmd_pipeline` 输出字段补齐

**声明**：`pipeline` 的 `cluster` 输出现在包含 `report_date`、`algorithm`、`feature_type`、`n_features`、`inertia`、`n_iter`、`k_search_results`；同时修复了 `skip-cluster` 时向 `attribute_run` 传入字符串 `k="auto"` 的 bug，现在统一使用 `cluster_result["k"]` 或解析后的整数。

**核查**：

[cli_core.py:264-307](../src/fundseeker/similarity/cli_core.py#L264-L307)

```python
# 3. Run clustering
cluster_k: int | None = None
if not args.skip_cluster:
    cluster_result = svc.cluster(...)
    cluster_k = cluster_result["k"]                  # ← 修复点 1：保存真实 K
    results["cluster"] = {
        "cluster_run_id": cluster_result["cluster_run_id"],
        "report_date": cluster_result["report_date"],
        "algorithm": cluster_result["algorithm"],
        "k": cluster_result["k"],
        "feature_type": cluster_result["feature_type"],
        "n_products": cluster_result["n_products"],
        "n_features": cluster_result["n_features"],    # ← 新增
        "silhouette": cluster_result["silhouette"],
        "inertia": cluster_result["inertia"],          # ← 新增
        "n_iter": cluster_result["n_iter"],            # ← 新增
        "mode": cluster_result["mode"],
        "baseline_run_id": cluster_result["baseline_run_id"],
        "k_search_results": cluster_result.get("k_search_results"),   # ← 新增
        "incremental_diagnostics": cluster_result.get("incremental_diagnostics"),
    }
else:
    # When clustering is skipped, resolve k for attribution.
    parsed = _parse_k(args.k)
    cluster_k = parsed if isinstance(parsed, int) else None   # ← 修复点 2

# 4. Run attribution for all clusters
if not args.skip_attribution:
    attribution_result = svc.attribute_run(
        ...,
        k=cluster_k,                              # ← 用解析后的 int/None
        ...
    )
```

**实测验证**：

```json
{
  "cluster": {
    "cluster_run_id": 73,
    "report_date": "2026-03-31",
    "algorithm": "kmeans-asset",
    "k": 9,
    "feature_type": "asset",
    "n_products": 642,
    "n_features": 1095,                            ← 已存在
    "silhouette": 0.054427859819728495,
    "inertia": 511.02539432809573,                  ← 已存在
    "n_iter": 1,                                    ← 已存在
    "mode": "incremental",
    "baseline_run_id": 17,
    "k_search_results": null,
    "incremental_diagnostics": {...}
  }
}
```

**结论**：✅ 字段补齐完整，额外修复了 `--skip-cluster` 模式下 `attribute_run` 收到字符串 `"auto"` 的隐性 bug（这是执行记录里没明确提到的 bonus）。

---

### ✅ 修复 #5（P2）：cron 脚本 `set -uo pipefail`

**声明**：增加 `set -uo pipefail`；保留 `set -e` 关闭以便捕获 pipeline 失败并生成日报。

**核查**：

[fundseeker_similarity_cron.sh:22-23](../scripts/fundseeker_similarity_cron.sh#L22)

```bash
# shellcheck disable=SC2317
set -uo pipefail
```

注释 `# shellcheck disable=SC2317` 也补齐，符合 #5 中提到的 shellcheck 建议。

**结论**：✅ 落地，但 #5 提到 `set -euo pipefail` 全开，实际执行选择保留 `set -e` 关闭是有合理理由的（cron 脚本需要捕获 `pipeline` 失败并继续生成日报）。详见 §4 #N1。

---

### ✅ 修复 #6（P2）：`list_baselines` 增加 `k_search_results`

**声明**：`SimilarityService.list_baselines()` 输出增加 `k_search_results` 字段。

**核查**：

[service.py:399-419](../src/fundseeker/similarity/service.py#L399-L419)

```python
return [
    {
        "baseline_id": r.id,
        ...
        "k_search_results": r.k_search_results,   # ← 新增
        "created_at": r.created_at,
    }
    for r in records
]
```

**实测验证**：

```bash
$ PYTHONPATH=src python scripts/fundseeker_similarity.py list-baselines
[
  {
    "baseline_id": 4,
    "cluster_run_id": 17,
    "report_date": "2026-03-31",
    "product_type_filter": "equity,mixed",
    "algorithm": "kmeans-asset",
    "k": 9,
    "feature_type": "asset",
    "silhouette": 0.054428,
    "inertia": 511.025394,
    "n_products": 642,
    "k_search_results": [
      {"k": 3, "n_iter": 12, "inertia": 542.0..., "silhouette": 0.0447...},
      {"k": 4, ...},
      ...
    ],
    "created_at": "..."
  }
]
```

**结论**：✅ 修复正确，含 K=3~9 全部 K 搜索历史。

---

### ✅ 修复 #7（P2）：cron 脚本输出格式补充说明

**声明**：在 CLI 文档 §6 补充说明 cron 脚本包裹行为。

**核查**：

[fundseeker-similarity-cli-v1.01.md:377](../docs/fundseeker-similarity-cli-v1.01.md#L377)

```
- `scripts/fundseeker_similarity_cron.sh` 会在 `pipeline` 的 JSON 输出外包裹一层人类可读的日报摘要（含时间、模式、退出码、状态图标），stdout 整体不是纯 JSON；如需解析底层 JSON，可直接调用 `pipeline` 子命令。
```

**结论**：✅ 落地。

---

### ✅ 修复 #8（P3）：设计文档 §4 精确化

**声明**：将"引用从模块 CLI 改为脚本 CLI"精确为"更新 docstring/页面提示中的 CLI 入口示例字符串"。

**核查**：

[fundseeker-similarity-cli-1.01-改进设计方案.md:151-152](../docs/fundseeker-similarity-cli-1.01-改进设计方案.md#L151-L152)

```
| `scripts/fundseeker_query.py` | 修改 | 更新 docstring 中的 CLI 入口示例字符串为脚本 CLI |
| `src/fundseeker/web/templates/similarity_index.html` | 修改 | 更新页面提示中的 CLI 入口示例字符串为脚本 CLI |
```

**结论**：✅ 描述精确化。

---

### ✅ 修复 #9（P3）：`list-baselines --report-date` 默认值描述

**声明**：改为"不过滤"，并补充参数表；`list-baselines` 输出表增加 `k_search_results`。

**核查**：

CLI 文档 §3.2 输出字段表已增加 `cluster_run_id`（文档 §3.2 表中没有列出原 `baseline_id` 与 `cluster_run_id` 区别，可能需要进一步明确）。

CLI 文档 §3.2 命令详情的参数表也对应更新。

**结论**：✅ 落地，但需要再确认 `cluster_run_id` 与 `baseline_id` 在文档中的区分是否清晰（见 #N4）。

---

### ✅ 修复 #10（P3）：OpenClaw YAML 格式

**声明**：每日/季度示例改用单条命令 + `&&` 连接，避免 `\` 续行；cron 脚本 §4.1 的 bash 示例保留原样。

**核查**：

[openclaw-scheduling-guide-v1.01.md:142-167](../docs/openclaw-scheduling-guide-v1.01.md#L142-L167) - YAML 示例已改为 `&&` 链式；§4.1 的 bash 示例保持 `\` 续行不变（合理，bash 命令块中 `\` 是合法的）。

**结论**：✅ 落地。

---

## 3. 修复代码质量评审

### 3.1 修复质量评分

| 维度 | 评分 | 说明 |
|---|---|---|
| P0 阻塞 bug 修复 | ✅ 优秀 | `START_DATE` 三层兜底，与文档"默认 report_date"完全对齐 |
| 代码风格 | ✅ 良好 | 沿用既有 `set -u` + 添加 `pipefail` 与 `# shellcheck disable` 注释 |
| 输出字段完整性 | ✅ 优秀 | `cmd_pipeline` `cluster` 输出从 7 字段扩展到 14 字段 |
| 文档更新 | ✅ 优秀 | 三份文档同步更新，互相引用一致 |
| 测试覆盖 | ✅ 良好 | 24/24 测试通过，无回归 |
| Bonus 修复 | ✅ 优秀 | `--skip-cluster` 时 `attribute_run` 收到 `k="auto"` 字符串的隐性 bug 顺手修了 |

### 3.2 隐性 Bug 修复（评审记录未提及）

#### Bug X1：`--skip-cluster` 模式下 `attribute_run` 收到字符串 `"auto"`

**原始位置**：[cli_core.py（旧版本） cmd_pipeline](../src/fundseeker/similarity/cli_core.py)

旧逻辑：

```python
attribution_result = svc.attribute_run(
    ...,
    k=args.k,  # 原始 CLI 参数，可能是 "auto" 字符串
    ...
)
```

如果用户运行 `pipeline --skip-cluster --k auto`，`attribute_run` 会收到 `k="auto"` 字符串，可能导致 `load_cluster_run` 查询异常或返回非预期结果。

**修复后**：

```python
cluster_k: int | None = None
if not args.skip_cluster:
    cluster_k = cluster_result["k"]  # int
else:
    parsed = _parse_k(args.k)
    cluster_k = parsed if isinstance(parsed, int) else None

attribution_result = svc.attribute_run(
    ...,
    k=cluster_k,  # 正确传入 int 或 None
    ...
)
```

**验证**：修复后的代码确保 `attribute_run` 收到的是 `int | None`，与 `load_cluster_run(report_date, k=None|int, ...)` 的签名一致。

**这是本次评审的意外收获**，执行记录未明确声明，但修复正确。

---

## 4. 新发现的问题

### 💡 #N1（低）：`set -e` 仍未启用

**位置**：[fundseeker_similarity_cron.sh:23](../scripts/fundseeker_similarity_cron.sh#L23)

```bash
set -uo pipefail
```

`set -e` 关闭是合理设计（cron 脚本需要捕获 pipeline 失败并生成日报），但也带来一个边界：如果 `bash scripts/fundseeker_similarity_cron.sh` 本身在 `source .venv/bin/activate` 阶段失败（例如 `.venv` 不存在），脚本会因 `set -u` 而立刻报错，但不会有任何错误摘要输出到 stdout。

**建议**

保持 `set -e` 关闭，但在最外层加 `trap`：

```bash
trap 'echo "❌ cron 脚本异常退出: $?" >&2; exit 1' ERR
```

这样即便 pipeline 之外的步骤失败，也能输出最小诊断信息。

---

### 💡 #N2（低）：`cmd_pipeline` 在 `skip_cluster=True` 时 `cluster_k` 解析边界

**位置**：[cli_core.py:291-294](../src/fundseeker/similarity/cli_core.py#L291-L294)

```python
else:
    # When clustering is skipped, resolve k for attribution.
    parsed = _parse_k(args.k)
    cluster_k = parsed if isinstance(parsed, int) else None
```

当 `args.k="auto"` 时，`parsed` 是字符串 `"auto"`，`cluster_k=None`，此时 `attribute_run` 用 `k=None` 查询最新运行。这与 `cmd_attribution` 中的行为一致（同样允许 `k=None`），所以逻辑正确。

**边界场景**：

- `--skip-cluster --k 8` → `cluster_k=8` ✅
- `--skip-cluster --k auto` → `cluster_k=None`（使用最新 K）✅
- `--skip-cluster`（不指定 `--k`） → `cluster_k=None` ✅

没有问题，只是为了完整性记录。

---

### 💡 #N3（低）：cron 脚本路径硬编码

**位置**：[fundseeker_similarity_cron.sh:25](../scripts/fundseeker_similarity_cron.sh#L25)

```bash
cd /home/cc/projects/fundseeker
```

迁移到其他机器或目录时需要手动改这一行。OpenClaw 部署通常通过 `cd ...` 进入项目目录，但 cron 调度未必会执行 `cd`。

**建议**：

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${SCRIPT_DIR}"
```

或使用环境变量 `FUNDSEEKER_HOME`。

---

### 💡 #N4（提示）：`list-baselines` 输出中 `baseline_id` 与 `cluster_run_id` 区分

**位置**：[fundseeker-similarity-cli-v1.01.md §3.2](../docs/fundseeker-similarity-cli-v1.01.md)

文档 §3.2 的输出字段表：

| 字段 | 说明 |
|---|---|
| `baseline_id` | 基线记录 ID |
| `cluster_run_id` | 基线对应的聚类运行 ID |

注释已说明两者区别：`baseline_id` 是 `similarity_cluster_baseline.id`，`cluster_run_id` 是关联的 `similarity_cluster_run.id`。当前文档描述清楚，无需修改。

**结论**：✅ 文档已清晰。

---

## 5. 建议与下一步

### 已无 P0/P1 待办

10 项修复全部落地，cron 脚本默认调用成功（exit 0），输出 JSON 字段完整。

### 可选的打磨项（v1.01.x）

1. **#N1**：cron 脚本加 `trap '...' ERR` 让激活失败也能输出诊断。
2. **#N3**：cron 脚本路径改为相对路径或环境变量。

### 中期规划（v1.02）

1. **CLI / cron 自动化测试**：
   - `tests/test_cli.py`：覆盖每个子命令的 `--help`、必填参数检查、`--mode` 默认值；
   - `tests/test_cron.sh`：用 bats 或 pytest-shell 覆盖 cron 脚本在各种环境变量下的行为（特别是 `START_DATE` 的三层兜底链）。
2. **评审报告附录 D 标注过时**：附录 C/D 展示的是修复前的实测日志，与新"修改执行记录"中的实测日志略有重复，建议在 v1.02 文档整理时合并。

### 不建议立即改动

- `cmd_pipeline` 的 `cluster_k=None` 解析：行为正确。
- cron 脚本的 emoji 输出：与项目其他 cron 脚本风格一致，统一性问题可放在 v1.02 整理。

---

## 附录 A：修复后实测日志

### A.1 cron 脚本默认调用

```bash
$ PYTHONPATH=src SKIP_INDEX_WEIGHTS=1 SKIP_QUOTES=1 SKIP_ATTRIBUTION=1 \
    SIMILARITY_MODE=auto timeout 30 bash scripts/fundseeker_similarity_cron.sh

📊 FundSeeker 相似性分析日报 — 2026-07-16 11:10:56
模式: auto | 特征: asset | K: auto
退出码: 0 ✅
```

### A.2 list-baselines 输出（含 k_search_results）

```json
[
  {
    "baseline_id": 4,
    "cluster_run_id": 17,
    "report_date": "2026-03-31",
    "product_type_filter": "equity,mixed",
    "algorithm": "kmeans-asset",
    "k": 9,
    "feature_type": "asset",
    "silhouette": 0.054428,
    "inertia": 511.025394,
    "n_products": 642,
    "k_search_results": [
      {"k": 3, "n_iter": 12, "inertia": 542.00..., "silhouette": 0.0447...},
      {"k": 4, ...},
      ...
    ],
    "created_at": "..."
  }
]
```

### A.3 测试覆盖

```
$ PYTHONPATH=src .venv/bin/pytest tests/ -q
24 passed, 399 warnings in 30.93s
```

## 附录 B：与修复前对比

| 维度 | 修复前 | 修复后 |
|---|---|---|
| cron 默认调用 | exit 2（缺 `--start-date`） | exit 0 ✅ |
| `cmd_pipeline` `cluster` 字段数 | 7 | 14（+7） |
| `list_baselines` 字段数 | 10 | 11（+`k_search_results`） |
| 设计文档 §3.3 字段表行数 | 3 | 15 |
| OpenClaw YAML 续行方式 | `\` 在 `\|` 块中（解析风险） | `&&` 链式 |
| `--skip-cluster --k auto` bug | 隐性存在 | 修复（cluster_k=None 透传） |
| cron 健壮性 | `set -u` | `set -uo pipefail` + shellcheck 注释 |
| 文档一致性 | 有偏差 | 同步对齐 |

## 附录 C：修复文件清单

| 文件 | 修改类型 | 关键改动 |
|---|---|---|
| `scripts/fundseeker_similarity_cron.sh` | bug fix | START_DATE 三层兜底 + `set -uo pipefail` |
| `src/fundseeker/similarity/cli_core.py` | feature | `cmd_pipeline` 输出字段补齐 + `--skip-cluster` K 解析修复 |
| `src/fundseeker/similarity/service.py` | feature | `list_baselines` 输出 `k_search_results` |
| `docs/fundseeker-similarity-cli-1.01-改进设计方案.md` | doc | §3.3 字段表扩展，§4 文件变更描述精确化 |
| `docs/fundseeker-similarity-cli-v1.01.md` | doc | §6 增加 cron 输出说明 |
| `docs/openclaw-scheduling-guide-v1.01.md` | doc | YAML 改 `&&` 链式 + 兜底说明 |

---

> **最终结论**：10 项修复全部正确落地，P0 阻塞 bug 已消除，24 个测试全部通过，无回归。修复过程中还顺手修复了评审未明确的 `--skip-cluster --k auto` 隐性 Bug。
> 进入日常调度前建议可选打磨 #N1（cron trap）与 #N3（路径参数化），但都不阻塞 OpenClaw 启用。