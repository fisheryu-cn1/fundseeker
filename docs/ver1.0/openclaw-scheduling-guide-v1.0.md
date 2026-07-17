# FundSeeker OpenClaw 定时调度指南

## 概述

FundSeeker 提供一个统一的命令行入口 `scripts/fundseeker_cli.py`，适合被 OpenClaw 或其他定时调度工具调用。每次执行完成后，程序会在标准输出（stdout）打印一份结构化的信息收集情况汇总报告，供 Agent 判断是否需要进行后续处理。

## 前置要求

1. **工作目录**: `/home/cc/projects/fundseeker`
2. **Python 环境**: 项目虚拟环境 `.venv`
3. **数据库**: PostgreSQL 已启动，数据库 `fundseeker` 可连接
4. **依赖**: 已通过 `pip install -r requirements.txt` 安装

## 统一入口

```bash
cd /home/cc/projects/fundseeker
source .venv/bin/activate
PYTHONPATH=src python scripts/fundseeker_cli.py <command> [options]
```

## 可用命令

### 1. 初始化数据库表

首次部署或新增表结构后执行：

```bash
PYTHONPATH=src python scripts/fundseeker_cli.py init-db
```

### 2. 查看当前数据汇总报告（只读）

不执行任何采集，仅查询数据库并输出报告：

```bash
PYTHONPATH=src python scripts/fundseeker_cli.py report
```

### 3. 执行采集任务

#### 采集所有数据（完整每日任务）

```bash
PYTHONPATH=src python scripts/fundseeker_cli.py collect --all
```

该命令会依次执行：
- 所有基金公司产品列表 + 最新净值采集
- 所有银行理财子公司产品列表 + 最新净值采集
- 全球主要市场行情（指数 + 大宗商品）采集
- 所有基金公司的季度持仓采集

#### 仅采集基金公司与净值

```bash
PYTHONPATH=src python scripts/fundseeker_cli.py collect --funds
```

覆盖机构：广发基金（GF）、华夏基金（ChinaAMC）、易方达基金（YFD）、汇添富基金（HTF）。

#### 仅采集银行理财子公司与净值

```bash
PYTHONPATH=src python scripts/fundseeker_cli.py collect --bank-wm
```

覆盖机构：建信理财（JX）、招银理财（ZY）、中银理财（BOC）、浦银理财（SPD）、信银理财（CITIC）、光大理财（CEB，当前跳过）。

#### 仅采集持仓数据

```bash
PYTHONPATH=src python scripts/fundseeker_cli.py collect --holdings
```

默认会跳过已存在持仓报告的产品。如需强制重新采集，加上 `--no-skip-existing`：

```bash
PYTHONPATH=src python scripts/fundseeker_cli.py collect --holdings --no-skip-existing
```

#### 仅采集市场行情

```bash
PYTHONPATH=src python scripts/fundseeker_cli.py collect --market-quotes
```

采集国内（上证、深证、创业板、沪深300）、香港（恒生）、美国（道琼斯、纳斯达克、标普500）主要指数，以及布伦特原油、纽约黄金实时行情。

#### 采集指定日期的市场行情

指数类行情支持历史日期回溯：

```bash
PYTHONPATH=src python scripts/fundseeker_cli.py collect --market-quotes --market-date 2026-06-30
```

大宗商品行情仅支持数据源返回的当前交易日，指定历史日期时若数据源未返回该日数据则跳过。

#### 强制重新采集产品与净值

默认情况下，如果某机构当天已经采集过产品列表和净值，对应任务会被标记为 `skipped` 并跳过网络请求。如需强制重新采集，加上 `--force`：

```bash
PYTHONPATH=src python scripts/fundseeker_cli.py collect --fund GF --force
PYTHONPATH=src python scripts/fundseeker_cli.py collect --all --force
```

```bash
PYTHONPATH=src python scripts/fundseeker_cli.py collect --holdings --no-skip-existing
```

#### 采集单个机构

```bash
# 单个基金公司
PYTHONPATH=src python scripts/fundseeker_cli.py collect --fund GF

# 单个银行理财子
PYTHONPATH=src python scripts/fundseeker_cli.py collect --bank SPD

# 单个机构的持仓
PYTHONPATH=src python scripts/fundseeker_cli.py collect --holding-code GF --holding-years 1
```

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 所有任务成功完成（`skipped` 不算失败） |
| 1 | 至少有一个采集任务失败 |
| 2 | 命令行参数错误 |

OpenClaw 可以根据退出码决定是否触发告警或人工复核。注意：`skipped` 表示当天已有数据、无需重复采集，属于正常状态。

## 输出报告格式

程序在标准输出打印的报告包含以下部分：

### 头部信息

- 报告生成时间
- 最新产品采集日期

### 本次执行任务

列出本次实际执行的子任务及结果：

```text
本次执行任务:
  [✓] fund_company:GF: success, records=0, duration=3.9s
  [✓] bank_wm:SPD: success, records=13758, duration=15.4s
  [⊘] fund_company:YFD: skipped, records=0, duration=0.0s
  [✗] bank_wm:CEB: failed, records=0, duration=1.2s
      error: ...
```

图标含义：
- `✓` success：成功采集并写入新数据
- `⊘` skipped：当天已有数据，未发起网络请求
- `✗` failed：采集失败，需查看 error 详情

### 数据库总体情况

```text
数据库总体情况:
  产品总数: 32439
  有净值产品: 26134 (80.6%)
  有持仓产品: 1700 (5.2%)
  净值记录数: 26134
  持仓记录数: 16458
```

### 各机构覆盖情况

```text
各机构覆盖情况:
  机构                 产品      有净值      有持仓
  GF                798      778      484
  ChinaAMC          770      716      464
  ...
```

### 近 7 天失败任务

列出最近 7 天内 `collection_log` 中 status = failed 的任务，便于 Agent 发现持续性问题。

### 后续建议

根据当前数据缺口自动生成建议，例如：

```text
后续建议:
  • 6305 个产品仍无净值记录，建议排查对应机构采集器或补充数据源。
  • 30739 个产品仍无持仓数据，可扩展债券持仓、资产配置及银行理财持仓采集。
  • 本次有 1 个任务失败，建议查看 collection_log 详情。
```

## OpenClaw 定时任务配置建议

### 推荐调度策略

| 任务 | 频率 | 建议命令 | 说明 |
|------|------|----------|------|
| 全量采集 | 每日一次 | `collect --all` | 抓取所有机构最新产品和净值、市场行情，并补充持仓 |
| 产品/净值补采 | 每 6 小时 | `collect --funds` 和 `collect --bank-wm` | 对失败机构重试 |
| 市场行情补采 | 每日一次（收盘后） | `collect --market-quotes` | 每个交易日收盘后补充当日行情，每日最多记录一次 |
| 持仓补采 | 每周一次 | `collect --holdings` | 季度持仓披露不频繁，每周增量补充即可 |
| 数据巡检 | 每小时 | `report` | 只读查询，输出当前状态 |

### OpenClaw 配置示例

```yaml
# 示例：每日 09:00 执行全量采集
jobs:
  fundseeker_daily:
    schedule: "0 9 * * *"
    command: |
      cd /home/cc/projects/fundseeker
      source .venv/bin/activate
      PYTHONPATH=src python scripts/fundseeker_cli.py collect --all
    timeout: 3600
    on_failure: notify
```

```yaml
# 示例：每小时巡检一次
jobs:
  fundseeker_health_check:
    schedule: "0 * * * *"
    command: |
      cd /home/cc/projects/fundseeker
      source .venv/bin/activate
      PYTHONPATH=src python scripts/fundseeker_cli.py report
    timeout: 60
    on_failure: notify
```

## Agent 判断后续工作的规则

OpenClaw Agent 读取 stdout 报告后，可按以下规则决策：

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

4. **如果"近 7 天失败任务"持续出现同一机构**：
   - 标记该机构为不稳定源。
   - 触发数据源健康检查或通知维护人员。

## 注意事项

1. **持仓采集耗时较长**：完整 `--holdings` 全量采集可能需要 30-60 分钟，建议设置足够大的 timeout。
2. **并发风险**：不要同时启动多个 `collect --holdings` 实例，否则可能在 `holding_security_info` 表上触发死锁。
3. **日志详情**：标准输出报告是摘要，完整错误信息写入 `collection_log.error_message` 字段，可连接数据库查询。
4. **环境变量**：数据库连接默认使用 `src/fundseeker/models/database.py` 中的 `DEFAULT_DB_URL`；如需覆盖，设置环境变量 `FUNDSEEKER_DATABASE_URL`。

## 常用调试命令

```bash
# 测试单个基金公司
PYTHONPATH=src python scripts/fundseeker_cli.py collect --fund GF

# 测试单个银行理财子
PYTHONPATH=src python scripts/fundseeker_cli.py collect --bank SPD

# 只检查当前状态
PYTHONPATH=src python scripts/fundseeker_cli.py report

# 强制重新采集某机构持仓
PYTHONPATH=src python scripts/fundseeker_cli.py collect --holding-code GF --no-skip-existing
```
