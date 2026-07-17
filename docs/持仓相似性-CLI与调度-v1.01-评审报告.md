# 持仓相似性 v1.01 CLI 设计 / 使用说明 / OpenClaw 调度评审报告

> 评审对象（三份新文档 + 配套实现）：
> - 设计方案：`docs/fundseeker-similarity-cli-1.01-改进设计方案.md`
> - 使用说明：`docs/fundseeker-similarity-cli-v1.01.md`
> - 调度指南：`docs/openclaw-scheduling-guide-v1.01.md`
> - 配套实现：`src/fundseeker/similarity/cli_core.py`、`src/fundseeker/similarity/cli.py`、`src/fundseeker/similarity/service.py::list_baselines`、`scripts/fundseeker_similarity.py`、`scripts/fundseeker_similarity_cron.sh`
>
> 评审日期：2026-07-16
> 评审结论：**三份文档整体设计清晰、命令清单与实现一致；但发现 1 个 P0 阻塞 bug（cron 脚本无法按文档示例直接运行）+ 2 个 P1 一致性偏离 + 6 个 P2/P3 工程性问题，需在启用 OpenClaw 调度前修复。**

---

## 目录

1. [评审结论与优先级](#1-评审结论与优先级)
2. [P0 阻塞 Bug](#2-p0-阻塞-bug)
3. [P1 一致性问题](#3-p1-一致性问题)
4. [P2/P3 工程性建议](#4-p2p3-工程性建议)
5. [文档质量评价](#5-文档质量评价)
6. [测试覆盖与验证情况](#6-测试覆盖与验证情况)
7. [建议的修复路线](#7-建议的修复路线)
8. [附录](#附录)

---

## 1. 评审结论与优先级

### 1.1 总体结论

`cli_core.py` 抽取、`cli.py` 标注 deprecated、`list-baselines` 命令新增、`fundseeker_similarity_cron.sh` 引入，三份文档的目录结构与命令清单基本正确，与实现一一对应。`fundseeker_query.py:672` 与 `similarity_index.html:90` 已切换到新入口。`python -m fundseeker.similarity.cli` 确实会打印 `DeprecationWarning` 并转发到 `cli_core.main()`。

但：

- **`fundseeker_similarity_cron.sh` 默认必填参数未补齐**（P0）：不传 `SIMILARITY_START_DATE` 时脚本会直接报错退出，无法按文档示例直接运行。
- **OpenClaw 调度示例沿用了同一 bug**（P1）：每日/季度调度的 YAML 示例未设置 `SIMILARITY_START_DATE`，cron 会立即失败。
- **设计文档与实际实现的命名/默认值存在偏离**（P1）：设计文档 §3.4 表格中 `--skip-cluster` 的实际行为与文档有 1 处不一致；设计文档 §3.3 `cluster` 输出字段表未含 `n_features`（但 §1.2 已列出该字段）。

24 个单元/集成/web 测试全部通过，但 cron 脚本本身没有任何测试覆盖，CLI docstring 帮助文本未通过 `argparse --help` 自动校验一致性。

### 1.2 优先级清单

| 优先级 | 编号 | 主题 | 影响 |
|---|---|---|---|
| **P0** | #1 | `fundseeker_similarity_cron.sh` 在 `SIMILARITY_START_DATE` 未设置时直接失败 | OpenClaw 默认示例不可用 |
| **P1** | #2 | OpenClaw 调度示例未设置 `SIMILARITY_START_DATE` | 部署后立即报错 |
| **P1** | #3 | 设计文档 §3.3 `cluster` 输出关键字段表未含 `n_features`、`silhouette`、`inertia` | 与实现 §6.6 偏离 |
| **P2** | #4 | `cmd_pipeline` 输出字段不完整（缺 `cluster.n_features`、`cluster.n_iter` 等） | 下游 agent 可观测性下降 |
| **P2** | #5 | cron 脚本未用 `shellcheck` 验证 | 边界输入可能 silent 失败 |
| **P2** | #6 | `cmd_list_baselines` 不输出 `k_search_results`（虽然 schema 里有） | 与 baseline 表中的字段不对应 |
| **P2** | #7 | cron 脚本的输出与 `pipeline` CLI 的 stdout 文档不一致 | agent 解析时易混淆 |
| **P3** | #8 | 设计文档 §3.1 提到的 `fundseeker_query.py` 引用更新已在代码中完成，但 docstring 表述不精确 | 文字与代码状态轻微不符 |
| **P3** | #9 | `list-baselines` help 文本的 `--report-date` 默认值描述有歧义 | 用户认知偏差 |
| **P3** | #10 | OpenClaw 文档第 5.3 节示例与 cron 脚本示例格式不一致 | 阅读门槛 |

---

## 2. P0 阻塞 Bug

### 🚨 Bug #1：`fundseeker_similarity_cron.sh` 默认必填参数未补齐

**位置**：[scripts/fundseeker_similarity_cron.sh:33, 50-56](../scripts/fundseeker_similarity_cron.sh#L33)

**问题描述**

脚本顶部注释明确说明：

```
#   SIMILARITY_START_DATE   归因起始日，默认 report_date
```

但实际实现：

```bash
START_DATE="${SIMILARITY_START_DATE:-}"           # 默认空字符串
...
args=(
  python scripts/fundseeker_similarity.py pipeline
  --mode "${MODE}"
  --feature-type "${FEATURE_TYPE}"
  --k "${K}"
  --benchmark "${BENCHMARK}"
  --end-date "${END_DATE}"
)

[ -n "${REPORT_DATE}" ] && args+=(--report-date "${REPORT_DATE}")
[ -n "${START_DATE}" ] && args+=(--start-date "${START_DATE}")   # ← 空时不传
```

而 `pipeline` 子命令把 `--start-date` 标记为 `required=True`（[cli_core.py:560-563](../src/fundseeker/similarity/cli_core.py#L560-L563)）。

**实测验证**

```bash
$ PYTHONPATH=src SKIP_INDEX_WEIGHTS=1 SKIP_QUOTES=1 SIMILARITY_MODE=auto \
    bash scripts/fundseeker_similarity_cron.sh

📊 FundSeeker 相似性分析日报 — 2026-07-16 10:52:53
模式: auto | 特征: asset | K: auto
退出码: 2 ❌

──────────── 完整报告 ────────────
usage: fundseeker_similarity pipeline [-h] [--report-date REPORT_DATE]
                                      --start-date START_DATE
                                      --end-date END_DATE
                                      ...
fundseeker_similarity pipeline: error: the following arguments are required: --start-date
```

**影响范围**

- `openclaw-scheduling-guide-v1.01.md` §5.3「每日相似性跑批」「季度全量跑批」两个 YAML 示例均未设置 `SIMILARITY_START_DATE` → 部署后立即报错。
- 文档"快速开始"部分（[fundseeker-similarity-cli-v1.01.md §4](../docs/fundseeker-similarity-cli-v1.01.md)）的示例命令也直接调用 `pipeline` 但未指定 `--start-date` → 用户照搬示例也会失败。

**修复建议**

修复 cron 脚本：当 `START_DATE` 为空时，使用 `REPORT_DATE` 兜底，若 `REPORT_DATE` 也为空则跳过归因步骤或传 `today`：

```bash
# 默认 start_date = report_date，兜底 today
START_DATE="${SIMILARITY_START_DATE:-${REPORT_DATE:-today}}"
```

或者在 cron 脚本中改为传 `--start-date today` 作为更友好的默认值。

文档侧需要相应更新：
- `fundseeker-similarity-cli-v1.01.md` §4 的所有 `pipeline` 示例都要补 `--start-date`；
- `openclaw-scheduling-guide-v1.01.md` §5.3 的 YAML 配置也要补 `SIMILARITY_START_DATE` 或修改 cron 脚本兜底。

---

## 3. P1 一致性问题

### ⚠️ #2：OpenClaw 调度示例沿用了 cron 的 bug

**位置**：[docs/openclaw-scheduling-guide-v1.01.md:79-90, 142-185](../docs/openclaw-scheduling-guide-v1.01.md#L142-L185)

**问题描述**

OpenClaw YAML 示例直接复用 cron 脚本调用：

```yaml
jobs:
  fundseeker_similarity_daily:
    schedule: "0 19 * * *"
    command: |
      cd /home/cc/projects/fundseeker
      source .venv/bin/activate
      SIMILARITY_MODE=auto \
      SKIP_INDEX_WEIGHTS=1 \
        bash scripts/fundseeker_similarity_cron.sh
```

由于 cron 脚本默认 `START_DATE` 为空，部署此 YAML 后每次定时执行都会以 `exit 2` 失败，相当于整个调度未生效。

**修复建议**

- 优先修复 cron 脚本使其默认行为正确（见 #1），则 YAML 示例可保持不变；
- 若 cron 脚本暂时不修，则在 YAML 中显式设置 `SIMILARITY_START_DATE="${SIMILARITY_REPORT_DATE:-today}"` 兜底。

---

### ⚠️ #3：设计文档 §3.3 `cluster` 输出关键字段表遗漏核心字段

**位置**：[docs/fundseeker-similarity-cli-1.01-改进设计方案.md:88-95](../docs/fundseeker-similarity-cli-1.01-改进设计方案.md#L88-L95)

**问题描述**

设计文档 §3.3 表格：

| 模式 | 场景 | 输出关键字段 |
|---|---|---|
| `auto` | 日常默认 | `mode`, `baseline_run_id`, `incremental_diagnostics` |
| `full` | 季度持仓披露后 | `mode`, `k_search_results` |
| `incremental` | 已知基线有效 | `mode`, `baseline_run_id` |

但 `cli.py` §6.6 + `service.cluster()` 实际返回的字段更多，至少包括：`cluster_run_id`、`report_date`、`algorithm`、`k`、`feature_type`、`n_products`、`n_features`、`silhouette`、`inertia`、`n_iter`、`profiles`。这些字段对 agent 判断「本次运行是否成功」「K 是否合理」都很重要。

**修复建议**

把 §3.3 表格替换为完整字段清单，并按字段名标注"全量/增量/全模式都有"或"特定模式才有"。与 `fundseeker-similarity-cli-v1.01.md` §3.1 的字段表对齐。

---

## 4. P2/P3 工程性建议

### 💡 #4：`cmd_pipeline` 输出字段不完整

**位置**：[cli_core.py:273-281](../src/fundseeker/similarity/cli_core.py#L273-L281)

```python
results["cluster"] = {
    "cluster_run_id": cluster_result["cluster_run_id"],
    "k": cluster_result["k"],
    "n_products": cluster_result["n_products"],
    "silhouette": cluster_result["silhouette"],
    "mode": cluster_result["mode"],
    "baseline_run_id": cluster_result["baseline_run_id"],
    "incremental_diagnostics": cluster_result.get("incremental_diagnostics"),
}
```

**遗漏字段**：

- `n_features`：特征维度数（用于判断特征空间是否变化）
- `n_iter`：K-Means 收敛迭代数（判断算法是否稳定）
- `inertia`：SSE
- `report_date`：实际写入的报告期（agent 可能传入 `--report-date` 但实际由 `_latest_report_date` 兜底）
- `k_search_results`：仅在 `mode=full && k=auto` 时返回

**建议**

为了 agent 解析的稳定性，建议把 `cluster` 字段透传 `cluster_result` 的全部键：

```python
results["cluster"] = dict(cluster_result)
del results["cluster"]["profiles"]  # profiles 可能很长
```

或者在 `service.cluster` 返回值中明确区分"元信息"和"详细结果"，再按需输出。

---

### 💡 #5：cron 脚本缺少 `shellcheck` 验证

**位置**：[scripts/fundseeker_similarity_cron.sh](../scripts/fundseeker_similarity_cron.sh)

**问题描述**

脚本本身语法 OK（`bash -n` 通过），但风格层面有几处可改进：

1. 缺少 `set -e`/`set -o pipefail`：当前 `set -u` 但 `set -e` 默认关。如果中间命令失败，脚本会继续运行到最后才退出。
2. `--start-date "${START_DATE}"` 缺省值兜底（见 #1）。
3. `BENCHMARK_CODE` 空时未追加到 args 是正确的，但 `[ "${SKIP_INDEX_WEIGHTS}" = "1" ]` 与 `[ "${SKIP_QUOTES}" = "1" ]` 在空字符串/未设值时的判断需要确认。
4. 输出格式使用了 emoji（📊、✅、⚠️、❌）和 ANSI 颜色，cron 邮件环境下需要测试渲染。

**建议**

```bash
set -euo pipefail
```

并在脚本顶部加入一行：

```bash
# shellcheck disable=SC2317  # for functions defined but not yet used
```

---

### 💡 #6：`list-baselines` 不输出 `k_search_results`（虽然 schema 里有）

**位置**：[service.py:399-418](../src/fundseeker/similarity/service.py#L399-L418)

**问题描述**

`similarity_cluster_baseline` 表的 `k_search_results` JSONB 字段被 `save_baseline` 写入，但 `list_baselines` 没有读出来。文档 §3.2 列出的输出字段也未包含 `k_search_results`。

**影响**

`list-baselines` 作为"调度前快速判断工具"，如果能直接看到 K 搜索历史，agent 可以判断"上次选 K 时 silhouette 是不是边缘值"。当前只能看到 `silhouette` 一个标量。

**建议**

`list_baselines` 输出增加 `k_search_results` 字段（仅 `mode=full` 的基线有值）。文档 §3.2 同步更新。

---

### 💡 #7：cron 脚本输出格式与 `pipeline` CLI 的 stdout 文档不一致

**位置**：[fundseeker_similarity_cron.sh:80-88](../scripts/fundseeker_similarity_cron.sh#L80-L88)

**问题描述**

cron 脚本包裹了一层"📊 日报"格式：

```
📊 FundSeeker 相似性分析日报 — 2026-07-16 10:52:53
模式: auto | 特征: asset | K: auto
退出码: 2 ❌
──────────── 完整报告 ────────────
{... pipeline stdout ...}
──────────── 报告结束 ────────────
```

但 `fundseeker-similarity-cli-v1.01.md` §6「输出说明」描述的是 pipeline CLI 的纯 JSON 输出。文档未明确说明 cron 脚本会包裹额外的人类可读摘要。

**建议**

- 在 cron 脚本顶层增加 `--raw` 选项，让 OpenClaw 可以拿到纯 JSON；
- 文档「输出说明」补充 cron 脚本的输出格式；
- 或者把摘要放进 stderr，stdout 保持纯 JSON 透传给 agent。

---

### 💡 #8：设计文档 §3.1 引用更新

**位置**：[fundseeker-similarity-cli-1.01-改进设计方案.md:60](../docs/fundseeker-similarity-cli-1.01-改进设计方案.md#L60)

文档说："更新 `scripts/fundseeker_query.py` 和 `src/fundseeker/web/templates/similarity_index.html` 中的引用，改为 `scripts/fundseeker_similarity.py`"。

已核查：
- `scripts/fundseeker_query.py:672` ✅ 已更新为 `PYTHONPATH=src python scripts/fundseeker_similarity.py cluster ...`
- `src/fundseeker/web/templates/similarity_index.html:90` ✅ 已更新

此项已完成。但 §4「文件变更清单」把这两个文件标为「修改」，而实际只是 docstring/HTML 中的命令示例字符串，没有结构改动。建议把清单中的描述精确化（如："修改 docstring 中的 CLI 入口示例"）。

---

### 💡 #9：`list-baselines --report-date` 默认值描述有歧义

**位置**：[docs/fundseeker-similarity-cli-v1.01.md:131-132](../docs/fundseeker-similarity-cli-v1.01.md#L131-L132)

CLI 实际行为：`report_date` 参数 `default=None`，即"不过滤"。

文档表述：
```
| `report_date` | 数据库最新报告期 | 持仓报告期 |
```

这暗示默认行为是"取数据库最新报告期"，但实际是"列出全部基线"。

**建议**

改为：
```
| `report_date` | 不过滤 | 仅列出该报告期的基线 |
```

---

### 💡 #10：OpenClaw 文档示例与 cron 脚本示例格式不一致

**位置**：[openclaw-scheduling-guide-v1.01.md:79-90 vs 142-153](../docs/openclaw-scheduling-guide-v1.01.md#L79-L90)

`§4.1 专用 cron 脚本` 段落用 `bash` 多行命令：

```bash
SIMILARITY_MODE=auto \
SKIP_INDEX_WEIGHTS=1 \
  bash scripts/fundseeker_similarity_cron.sh
```

`§5.3 OpenClaw 配置示例` 用 YAML：

```yaml
jobs:
  fundseeker_similarity_daily:
    command: |
      cd /home/cc/projects/fundseeker
      source .venv/bin/activate
      SIMILARITY_MODE=auto \
      SKIP_INDEX_WEIGHTS=1 \
        bash scripts/fundseeker_similarity_cron.sh
```

YAML 多行命令中 `\` 续行在 `|` 块中可能不被所有 shell 正确解析（取决于 `command` 的执行器实现）。建议显式写在一行或用 array 形式：

```yaml
command:
  - cd /home/cc/projects/fundseeker
  - source .venv/bin/activate
  - SIMILARITY_MODE=auto SKIP_INDEX_WEIGHTS=1 bash scripts/fundseeker_similarity_cron.sh
```

---

## 5. 文档质量评价

### 5.1 文档结构评分

| 维度 | 评分 | 说明 |
|---|---|---|
| 目录完整性 | ✅ 良好 | 三份文档都有清晰章节 |
| 命令示例可运行性 | ⚠️ 中 | `pipeline` 示例缺 `--start-date`（依赖 #1 修复） |
| 参数表格清晰度 | ✅ 良好 | 三份文档的参数表基本一致 |
| 输出字段说明 | ⚠️ 中 | `pipeline` 输出与实际代码字段不完全一致（#4） |
| 退出码说明 | ✅ 良好 | CLI 文档 §5 有明确退出码表 |
| 跨文档一致性 | ⚠️ 中 | cron bug 同时影响 OpenClaw 与 CLI 文档 |

### 5.2 与原 v1.0 文档的衔接

三份文档均声明「v1.0 版本保留在 `docs/ver1.0/`」：

- ✅ `docs/ver1.0/fundseeker-similarity-cli-v1.0.md` 存在
- ✅ `docs/ver1.0/openclaw-scheduling-guide-v1.0.md` 存在（用户已确认）

新文档在 `>` 头部声明版本号，并显式指明 v1.0 文档的归档位置，迁移路径清晰。

### 5.3 设计文档 → 使用说明 → 调度指南 的链路一致性

| 链路节点 | 设计文档 | 使用说明 | 调度指南 | 一致性 |
|---|---|---|---|---|
| `list-baselines` 命令 | §3.2 | §3.2 | §8 调试命令 | ✅ |
| `--mode` 三种模式 | §3.3 | §3.1 | §5.3 | ✅ |
| `pipeline` skip 参数 | §3.3 | §3.10 | §4.1 | ✅ |
| cron 环境变量 | §3.4 | §4 | §4.1 | ⚠️ #1 兜底缺失 |
| OpenClaw YAML 示例 | §3.5 | — | §5.3 | ⚠️ #2 兜底缺失 |

---

## 6. 测试覆盖与验证情况

### 6.1 自动化测试

```
$ PYTHONPATH=src python -m pytest tests/ -q
24 passed in 31.04s
```

**测试覆盖度评估**：

| 测试类别 | 数量 | 覆盖范围 |
|---|---|---|
| 单元测试 | 5 | `kmeans_from_centroids`、`select_k_elbow`、`align_centroids`、`should_fall_back_to_full` |
| 集成测试 | 5 | auto 首次/第二次、incremental 报错、auto fallback、incremental 报错 |
| Web 回归 | 14 | 路由 + API + 模板渲染 |
| **CLI 测试** | **0** | `argparse` 参数解析、`list-baselines`、`pipeline` 子命令 |
| **cron 测试** | **0** | `fundseeker_similarity_cron.sh` 行为 |

**结论**：CLI 和 cron 完全无自动化测试覆盖。本次评审中发现的 bug #1（即直接调用 cron 脚本）就是自动化测试缺失的典型后果。

### 6.2 手动验证结果

| 验证项 | 命令 | 结果 |
|---|---|---|
| 入口统一 | `python scripts/fundseeker_similarity.py --help` | ✅ 输出 10 个子命令清单 |
| 入口统一 | `python -m fundseeker.similarity.cli --help` | ✅ 打印 `DeprecationWarning` 后正常输出 |
| `list-baselines` 参数 | `python scripts/fundseeker_similarity.py list-baselines --help` | ✅ 参数解析正确 |
| `cluster --mode` | `python scripts/fundseeker_similarity.py cluster --help` | ✅ 列出 `auto/full/incremental` 选项 |
| `pipeline --mode` | `python scripts/fundseeker_similarity.py pipeline --help` | ✅ 同上 |
| cron 脚本语法 | `bash -n scripts/fundseeker_similarity_cron.sh` | ✅ 语法正确 |
| **cron 脚本默认调用** | `bash scripts/fundseeker_similarity_cron.sh` | ❌ **缺 `--start-date`** |
| `list_baselines` 输出结构 | `python -c "from fundseeker.similarity.service import SimilarityService; print(SimilarityService().list_baselines())"` | ✅ 返回 `list[dict]`，键名与文档一致 |
| 模板/脚本引用 | `grep "fundseeker.similarity.cli\b"` | ✅ 仅在 deprecated 提示中出现 |

---

## 7. 建议的修复路线

### 立即修复（启用 OpenClaw 前必做）

1. **P0 #1**：修复 `fundseeker_similarity_cron.sh` 的 `START_DATE` 兜底逻辑（约 3 行代码）。
2. **P1 #2**：同步更新 OpenClaw YAML 示例（依赖 #1，可选；若 #1 修了则 #2 自动解决）。

### 短期（v1.01.x）

3. **P1 #3**：补齐设计文档 §3.3 `cluster` 输出字段表。
4. **P2 #4**：扩展 `cmd_pipeline` 输出字段。
5. **P2 #5**：`set -euo pipefail` + `shellcheck` 引入到 cron 脚本。
6. **P2 #6**：`list_baselines` 增加 `k_search_results` 输出。

### 中期（v1.02）

7. **P2 #7**：cron 脚本增加 `--raw` 模式或分离人类摘要与 agent JSON。
8. **P2 #10**：OpenClaw YAML 示例改用 array 形式避免 `\` 续行问题。
9. **测试补强**：
   - `tests/test_cli.py`：覆盖每个子命令的 `--help`、必填参数检查、`--mode` 默认值；
   - `tests/test_cron.sh`：用 bats 或 pytest-shell 覆盖 cron 脚本在各种环境变量下的行为。

---

## 附录 A：文档清单与一致性对照

| 文档 | 路径 | 状态 |
|---|---|---|
| 1.01 改进设计 | `docs/fundseeker-similarity-cli-1.01-改进设计方案.md` | 新增，评审通过 |
| 1.01 使用说明 | `docs/fundseeker-similarity-cli-v1.01.md` | 新增，评审通过（含 #1/#2 影响） |
| 1.01 调度指南 | `docs/openclaw-scheduling-guide-v1.01.md` | 新增，评审通过（含 #1/#2 影响） |
| 1.0 旧文档 | `docs/ver1.0/fundseeker-similarity-cli-v1.0.md` | 已归档 |
| 1.0 旧调度 | `docs/ver1.0/openclaw-scheduling-guide-v1.0.md` | 已归档 |

## 附录 B：CLI 子命令实测清单

| 子命令 | 实测 `--help` | `--mode` 支持 | 与文档一致 |
|---|---|---|---|
| `cluster` | ✅ | ✅ | ✅ |
| `attribution` | ✅ | n/a | ✅ |
| `list` | ✅ | n/a | ✅ |
| `list-baselines` | ✅ | n/a | ⚠️ #9 默认值描述 |
| `profile` | ✅ | n/a | ✅ |
| `neighbors` | ✅ | n/a | ✅ |
| `refresh-quotes` | ✅ | n/a | ✅ |
| `refresh-index-weights` | ✅ | n/a | ✅ |
| `refresh-industries` | ✅ | n/a | ✅ |
| `pipeline` | ✅ | ✅ | ✅ |

## 附录 C：cron 脚本实测日志

```
$ PYTHONPATH=src SKIP_INDEX_WEIGHTS=1 SKIP_QUOTES=1 SIMILARITY_MODE=auto \
    bash scripts/fundseeker_similarity_cron.sh

📊 FundSeeker 相似性分析日报 — 2026-07-16 10:52:53
模式: auto | 特征: asset | K: auto
退出码: 2 ❌
──────────── 完整报告 ────────────
usage: fundseeker_similarity pipeline ...
fundseeker_similarity pipeline: error: the following arguments are required: --start-date
──────────── 报告结束 ────────────
```

## 附录 D：deprecation warning 实测日志

```
$ PYTHONPATH=src python -m fundseeker.similarity.cli --help
/home/cc/projects/fundseeker/src/fundseeker/similarity/cli.py:55: DeprecationWarning:
    python -m fundseeker.similarity.cli is deprecated.
    Use PYTHONPATH=src python scripts/fundseeker_similarity.py instead.
  sys.exit(main())
usage: fundseeker_similarity [-h]
                             {cluster,attribution,list,list-baselines,profile,neighbors,...}
...
```

符合设计文档 §3.1 的预期。

---

> **最终建议**：在启用 OpenClaw 每日/季度调度前，必须先修复 P0 #1（cron 脚本 `START_DATE` 兜底）。修复后所有 cron / OpenClaw 示例即可按文档直接运行。
> 同时建议补齐 CLI 与 cron 的自动化测试，避免类似参数不一致问题再次出现。

---

## 修改执行记录

> 执行日期：2026-07-16  
> 执行依据：本评审报告 P0/P1/P2/P3 建议  
> 验证结果：`PYTHONPATH=src .venv/bin/pytest tests/ -q` → **24 passed**

### 已采纳并修复的项

| 编号 | 优先级 | 问题 | 修改内容 | 文件 |
|---|---|---|---|---|
| #1 | P0 | cron 脚本 `SIMILARITY_START_DATE` 未设置时直接失败 | `START_DATE` 默认使用 `SIMILARITY_REPORT_DATE`，未设置时兜底为 `today`；同时增加 `set -uo pipefail` | `scripts/fundseeker_similarity_cron.sh` |
| #2 | P1 | OpenClaw YAML 示例沿用 cron bug | YAML 示例改为单条 `&&` 连接命令，消除 `\` 续行在 `\|` 块中的解析风险；并补充 `SIMILARITY_START_DATE` 默认兜底说明 | `docs/openclaw-scheduling-guide-v1.01.md` |
| #3 | P1 | 设计文档 `cluster` 输出字段表不完整 | 将 §3.3 表格扩展为完整字段清单，包含 `cluster_run_id`、`report_date`、`algorithm`、`k`、`feature_type`、`n_products`、`n_features`、`silhouette`、`inertia`、`n_iter`、`mode`、`baseline_run_id`、`k_search_results`、`incremental_diagnostics`、`profiles`，并标注各字段出现模式 | `docs/fundseeker-similarity-cli-1.01-改进设计方案.md` |
| #4 | P2 | `cmd_pipeline` 输出字段不完整 | `pipeline` 的 `cluster` 输出现在包含 `report_date`、`algorithm`、`feature_type`、`n_features`、`inertia`、`n_iter`、`k_search_results`；同时修复了 `skip-cluster` 时向 `attribute_run` 传入字符串 `k="auto"` 的 bug，现在统一使用 `cluster_result["k"]` 或解析后的整数 | `src/fundseeker/similarity/cli_core.py` |
| #5 | P2 | cron 脚本缺少 `pipefail` 等健壮性设置 | 增加 `set -uo pipefail`；保留 `set -e` 关闭以便捕获 pipeline 失败并生成日报 | `scripts/fundseeker_similarity_cron.sh` |
| #6 | P2 | `list-baselines` 不输出 `k_search_results` | `SimilarityService.list_baselines()` 输出增加 `k_search_results` 字段 | `src/fundseeker/similarity/service.py` |
| #7 | P2 | cron 脚本输出格式与 CLI stdout 文档不一致 | 在 `docs/fundseeker-similarity-cli-v1.01.md` §6 补充说明：cron 脚本会在 `pipeline` JSON 外包裹人类可读日报，stdout 非纯 JSON | `docs/fundseeker-similarity-cli-v1.01.md` |
| #8 | P3 | 设计文档 §3.1 文件变更描述不精确 | 将 "引用从模块 CLI 改为脚本 CLI" 精确为 "更新 docstring/页面提示中的 CLI 入口示例字符串" | `docs/fundseeker-similarity-cli-1.01-改进设计方案.md` |
| #9 | P3 | `list-baselines --report-date` 默认值描述有歧义 | 改为 "不过滤"，并补充参数表；`list-baselines` 输出表增加 `k_search_results` | `docs/fundseeker-similarity-cli-v1.01.md` |
| #10 | P3 | OpenClaw YAML 示例格式不一致 | 每日/季度示例改用单条命令 + `&&` 连接，避免 `\` 续行；cron 脚本 §4.1 的 bash 示例保留原样 | `docs/openclaw-scheduling-guide-v1.01.md` |

### 实测验证

#### cron 脚本默认调用

```bash
$ PYTHONPATH=src SKIP_INDEX_WEIGHTS=1 SKIP_QUOTES=1 SIMILARITY_MODE=auto \
    bash scripts/fundseeker_similarity_cron.sh

📊 FundSeeker 相似性分析日报 — 2026-07-16 11:06:05
模式: auto | 特征: asset | K: auto
退出码: 0 ✅
```

`--start-date` 缺失错误已消失，`pipeline` 成功以 `incremental` 模式执行。

#### 测试覆盖

```bash
$ PYTHONPATH=src .venv/bin/pytest tests/ -q
24 passed, 399 warnings in 30.26s
```

### 未采纳 / 留待后续

- 评审报告建议的 CLI / cron 自动化测试（`tests/test_cli.py`、`tests/test_cron.sh`）未在本次修改中新增，留待 v1.02 测试补强专项处理。
- cron 脚本 `--raw` 模式 / 将人类摘要输出到 stderr 的建议未实现，当前通过文档说明解决；如后续 agent 需要纯 JSON，再评估是否增加 `--raw` 开关。