# FundSeeker 只读检索 CLI（fundseeker_query）

> 把 `http://127.0.0.1:5001` 展示界面的查询能力封装成一个可被 OpenClaw /
> Claude Code / 其他 Agent 调用的命令行工具。检索结果以 Markdown 文档形式
> 输出，便于 Agent 直接读取或交给 LLM 做后续分析。

## 快速上手

```bash
cd /home/cc/projects/fundseeker
PYTHONPATH=src python scripts/fundseeker_query.py <command> [options] [-o file.md]
```

- 默认输出到 stdout；加 `-o file.md` 写入文件。
- 输出文件最长 **2000 行**，超过会自动截断并在文末插入提示。
- 退出码：`0` 成功；`2` 参数错误；查询运行期异常被捕获并写入文档，
  不会导致进程崩溃。

## 子命令一览

| 子命令 | 作用 | 对应 Web 页面 |
|---|---|---|
| `dashboard` | 输出产品总数、净值/持仓覆盖、按机构和资产类型分布 | `/dashboard` |
| `filters` | 列出所有可筛选维度（机构、类型、市场、报告期…） | （页面顶栏下拉） |
| `search` | 按机构/类型/风险/关键字等检索产品 | `/` |
| `product <id>` | 单个产品的基本信息、净值、持仓、风格标签 | `/product/<id>` |
| `holdings` | 跨产品持仓检索（资产类型/市场/机构/最小权重…） | `/holdings` |
| `security <code>` | 通过资产代码查询标的元信息 | （无对应页） |

## 通用选项

| 选项 | 说明 |
|---|---|
| `-h`, `--help` | 子命令帮助 |
| `-o`, `--output PATH` | 写入文件而非 stdout；如内容被截断，stderr 会打印 `WARNING` |

## 子命令详细用法

### `dashboard`

打印数据总览。**不需要参数。**

```bash
PYTHONPATH=src python scripts/fundseeker_query.py dashboard
```

输出内容：
- 总体指标：产品总数、覆盖机构数、净值记录数、最近一次成功任务。
- 持仓覆盖：报告数、明细行数、有持仓产品数、占比、最新报告期、涉及机构。
- 按资产类型 / 按机构 / 机构×类型 的分布表。

### `filters`

打印所有筛选维度的合法值，便于构造后续查询。

```bash
PYTHONPATH=src python scripts/fundseeker_query.py filters
```

输出包括：
- 产品类型 / 风险等级 / 持仓资产类型 / 市场 的 `code — label` 列表。
- `distinct_institutions()` 返回的实际机构代码（按字母序）。
- `distinct_statuses()` 产品状态枚举。
- `distinct_holding_report_dates()` 最近的 12 个报告期。

### `search`

按多维度过滤产品列表。

| 参数 | 说明 |
|---|---|
| `--institution CODE` | 机构代码，如 `YFD` / `HTF` |
| `--type TYPE` | 产品类型，可选值见 `filters` 输出 |
| `--risk L1..L5` | 风险等级 |
| `--keyword`, `-q TEXT` | 匹配产品代码或名称（ILIKE） |
| `--status TEXT` | 状态过滤 |
| `--page N` | 第几页（默认 1） |
| `--page-size N` | 每页大小（默认 50，上限 200） |

```bash
# YFD 旗下所有股票型基金，写入文件
PYTHONPATH=src python scripts/fundseeker_query.py search \
    --institution YFD --type equity -o /tmp/yfd-equity.md
```

### `product <id>`

展示单个产品的完整画像。

| 参数 | 说明 |
|---|---|
| `product_id` | 产品主键 ID（必填） |
| `--report-id N` | 持仓报告 ID（默认取最新一份） |
| `--asset-type TYPE` | 仅展示该资产类型的持仓 |
| `--top10` | 仅展示前十大持仓 |
| `--nav-limit N` | 净值条数（默认 50） |

```bash
# 最新 Top10 持仓
PYTHONPATH=src python scripts/fundseeker_query.py product 332 --top10

# 指定一份历史报告
PYTHONPATH=src python scripts/fundseeker_query.py product 332 --report-id 684
```

输出包含：基本信息 / 净值时间序列 / 持仓报告列表 / 汇总指标 /
大类资产配置 / 持仓明细 / 风格标签。

### `holdings`

跨产品持仓检索，对应 Web `/holdings` 页面。

| 参数 | 说明 |
|---|---|
| `--asset-type TYPE` | 资产类型（stock / bond / fund / cash …） |
| `--market MKT` | 市场（SH / SZ / BJ / HK / US …） |
| `--institution CODE` | 机构过滤 |
| `--keyword`, `-q TEXT` | 匹配资产代码 / 名称 / 行业 |
| `--min-weight PCT` | **最小占净值百分数**（例如 1.5 表示 1.5%），内部自动 ÷100 |
| `--top10` | 仅前十大持仓 |
| `--report-date YYYY-MM-DD` | 限定报告期 |
| `--page N` | 第几页 |
| `--page-size N` | 每页大小（默认 50，上限 200） |

```bash
# SH 市场、占净值 ≥ 0.5% 的所有股票持仓
PYTHONPATH=src python scripts/fundseeker_query.py holdings \
    --asset-type stock --market SH --min-weight 0.5

# 所有基金在 2026 Q1 报告期的前十大持仓中包含"宁德时代"的记录
PYTHONPATH=src python scripts/fundseeker_query.py holdings \
    --keyword 宁德时代 --top10 --report-date 2026-03-31
```

> 💡 数据库中 `weight` 是小数（如 `0.07` 表示 7%），CLI 已做百分数 →
> 小数转换；如要 5% 及以上，传 `--min-weight 5`。

### `security <code>`

通过代码（+ 可选市场）反查标的元信息。

```bash
PYTHONPATH=src python scripts/fundseeker_query.py security 600519 --market SH
```

## 输出格式

每份结果都以 Markdown 组织，便于 LLM 阅读：

1. **顶部元信息** — 标题、生成时间、回显查询参数。
2. **结果摘要** — 总条数、当前页命中数。
3. **结果表** — Markdown 表格；长字符串自动截断（产品名 36 字符、资产名 22 字符、行业 12 字符）。
4. **截断提示** — 若内容超过 2000 行，追加：

   > ⚠️ **输出已截断**，超过 2000 行上限。请缩小筛选范围…

数字格式：
- 百分比统一保留 2 位小数（`0.70%`、`-0.02%`）。
- 金额按绝对值自适应 `万` / `亿` 后缀（`<1` 时保留 4 位小数）。

## 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 2 | 参数错误（如 `--report-date` 格式非 `YYYY-MM-DD`） |

> 备注：当前版本在查询运行期异常时把错误写进 Markdown 文档、仍返回 0，
> 以便 Agent 把整份输出一起消费；如需要严格退出码，可后续扩展。

## OpenClaw 调度建议

```yaml
jobs:
  # 每次有新需求时即时拉取
  fundseeker_query_product:
    command: |
      cd /home/cc/projects/fundseeker
      PYTHONPATH=src python scripts/fundseeker_query.py product \
        $PRODUCT_ID --top10 -o /tmp/product.md
    on_demand: true
```

## 常见问题

- **Q：为什么 `search` 结果有重复行？**
  `product_info` 是按 `collect_date` 切片快照的，每只产品可能有多行
  快照；这与 Web UI 行为一致。如要按"最新一份"过滤，请在 `search` 之后再
  调 `product <id>`，或对 SQL 直接去重（不在 CLI 范围）。

- **Q：`holdings --min-weight 5` 为什么返回 0 条？**
  CLI 把百分数转成小数传入查询；5 表示 500%，显然没数据。请传小数
  百分数（`0.5` = 0.5%）。

- **Q：如何把多份输出串起来？**
  加 `-o file.md` 写到文件，再用 `cat` 拼接或单独发回 Agent。

## 相关文件

- CLI 实现：`scripts/fundseeker_query.py`
- 被复用的查询函数：`src/fundseeker/web/queries.py`
- Web UI 模板：`src/fundseeker/web/templates/`
