# 当前会话环境备忘

## 会话标识

- **Session ID**: `wd_fundseeker_38cb04dd7dea`
- **工作目录**: `/home/cc/projects/fundseeker`
- **会话数据路径**: `/home/cc/.kimi-code/sessions/wd_fundseeker_38cb04dd7dea`

## 项目概况

- **项目名称**: fundseeker（理财产品统一数据采集方案）
- **代码路径**: `src/fundseeker/`
- **配置文件**: `config/institutions.yaml`
- **数据源文档**: `docs/ver1.0/data_sources-v1.0/`

## Python 环境

- **Python 版本**: 3.13.9
- **虚拟环境**: `.venv/`（位于项目根目录）
- **激活方式**: `source .venv/bin/activate`

### 关键依赖

| 包 | 版本 | 用途 |
|----|------|------|
| SQLAlchemy | 2.0.51 | ORM / 数据库操作 |
| psycopg2-binary | 2.9.12 | PostgreSQL 驱动 |
| requests | 2.34.2 | HTTP 请求 |
| playwright | 1.60.0 | 浏览器自动化 |
| PyYAML | 6.0.3 | YAML 配置解析 |
| json5 | 0.15.0 | JSON5 解析（浦银理财接口） |

## 数据库设置

- **数据库类型**: PostgreSQL
- **连接 URL**: `postgresql+psycopg2://user:password@localhost:5432/fundseeker`
- **环境变量**: 可通过 `FUNDSEEKER_DATABASE_URL` 覆盖，默认见 `src/fundseeker/models/database.py`
- **初始化脚本**: `scripts/init_db.py`（也可用 `fundseeker_cli.py init-db`）
- **核心表**:
  - `product_info`：产品基础信息（按日快照）
  - `product_nav`：产品净值时序
  - `product_return`：收益率记录
  - `product_fee`：费率结构
  - `collection_log`：采集任务日志
  - `holding_report`：持仓报告期
  - `product_holding`：持仓明细
  - `product_asset_allocation`：大类资产配置
  - `product_holding_summary`：持仓汇总指标
  - `holding_security_info`：证券基础信息维度表
  - `product_manager_style`：经理/产品风格标签（预留）
  - `market_quote`：全球主要市场行情（指数、大宗商品）

## 当前数据入库情况

### 各机构覆盖情况（按唯一产品代码统计）

| 机构 | 代码 | 产品数 | 有净值 | 有持仓 | 数据源 | 状态 |
|------|------|--------|--------|--------|--------|------|
| 浦银理财 | SPD | 7,967 | 5,791 | 0 | 浦银理财官网 | 完成 |
| 信银理财 | CITIC | 6,858 | 6,858 | 0 | 信银理财微信端 | 完成 |
| 建信理财 | JX | 4,323 | 4,235 | 0 | 建信理财官网 | 完成 |
| 广发基金 | GF | 798 | 778 | 484 | 东方财富基金 API | 完成 |
| 华夏基金 | ChinaAMC | 770 | 716 | 466 | 东方财富基金 API | 完成 |
| 中银理财 | BOC | 825 | 762 | 0 | 中银理财官网 | 完成 |
| 易方达基金 | YFD | 720 | 695 | 380 | 东方财富基金 API | 完成 |
| 汇添富基金 | HTF | 693 | 655 | 372 | 东方财富基金 API | 完成 |
| 招银理财 | ZY | 8 | 0 | 0 | 招银理财官网 | 完成 |
| 光大理财 | CEB | 5 | 0 | 0 | 中国理财网推荐 JSON | **已跳过** |

### 持仓数据总体情况

- `holding_report`: 1,700+ 条
- `product_holding`: 16,458 条
- `holding_security_info`: 1,484 条
- 持仓覆盖：1,702 个基金产品有股票持仓（约 7.4% 的 unique 产品）
- 持仓来源：天天基金网 F10 接口（前十大重仓股）
- 未覆盖产品：主要为债券型、FOF、QDII 及银行理财子产品

## 光大理财跳过说明

光大理财（CEB）全量采集暂被跳过，原因如下：

1. **中国理财网**:
   - 筛选页 `https://www.chinawealth.com.cn/lcweb/management/proScreen` 会触发文字点选验证码（如“请依次点击【雨,拉,刚】”）。
   - 完整搜索接口 `POST /lcw-fe-service/prod/search` 使用 RSA + AES + HMAC 加密，需要完成验证码后才会进行密钥交换 `/dcp/login/applyKey`。
   - 公开推荐 JSON 端点（`durationProduct_EN.json`、`retireProduct_EN.json`）数据量极小，仅能获取个位数样本。

2. **光大理财官网**:
   - `https://www.cebwm.com` 启用了瑞数 WAF，直接请求返回 `412 Precondition Failed`。

当前 `src/fundseeker/collectors/cebwm.py` 保留了基于中国理财网推荐 JSON 的占位采集器，后续如需全量覆盖，需要专门处理验证码或逆向加密接口。

## 常用命令

```bash
# 激活虚拟环境
source .venv/bin/activate

# 初始化数据库表
PYTHONPATH=src python scripts/fundseeker_cli.py init-db

# 统一入口：查看当前数据汇总报告
PYTHONPATH=src python scripts/fundseeker_cli.py report

# 统一入口：采集所有数据（基金 + 银行理财子 + 持仓）
PYTHONPATH=src python scripts/fundseeker_cli.py collect --all

# 统一入口：仅采集基金公司与净值
PYTHONPATH=src python scripts/fundseeker_cli.py collect --funds

# 统一入口：仅采集银行理财子公司与净值
PYTHONPATH=src python scripts/fundseeker_cli.py collect --bank-wm

# 统一入口：仅采集持仓数据
PYTHONPATH=src python scripts/fundseeker_cli.py collect --holdings

# 统一入口：采集市场行情（指数+大宗商品）
PYTHONPATH=src python scripts/fundseeker_cli.py collect --market-quotes

# 统一入口：采集指定日期的市场行情
PYTHONPATH=src python scripts/fundseeker_cli.py collect --market-quotes --market-date 2026-06-30

# 兼容旧脚本（仍可用）
PYTHONPATH=src python scripts/run_fund_company.py <CODE>
PYTHONPATH=src python scripts/run_bank_wm.py <CODE>
PYTHONPATH=src python scripts/run_holding_collection.py --code <CODE>

# 启动 Web 服务
PYTHONPATH=src python scripts/run_web.py
```

## 关键代码文件

| 文件 | 说明 |
|------|------|
| `scripts/fundseeker_cli.py` | 统一 CLI 入口，适合 OpenClaw 定时调用 |
| `src/fundseeker/runner.py` | 各采集任务的可复用 runner 函数 |
| `src/fundseeker/collectors/holding_base.py` | 持仓采集器基类 |
| `src/fundseeker/collectors/eastmoney_holding.py` | 天天基金持仓采集器 |
| `docs/ver1.0/openclaw-scheduling-guide-v1.0.md` | OpenClaw 定时调度使用说明 |

## 注意事项

- 浦银理财（SPD）和信银理财（CITIC）服务器使用了旧版 TLS/SSL 协商，已在 `src/fundseeker/utils/http.py` 中通过 `ssl_legacy` 开关启用 `OP_LEGACY_SERVER_CONNECT` 兼容。
- 采集脚本使用 `on_conflict_do_nothing`，同一机构 + 产品代码 + 采集日期的记录不会重复写入。
- `fundseeker_cli.py` 在运行产品/净值采集前会先检查当天是否已有数据：有则标记为 `skipped` 并跳过网络请求；如需强制重采，加 `--force`。
- `fundseeker_cli.py collect --all` 包含持仓采集，全量运行可能需要 30-60 分钟，OpenClaw 调度时建议 timeout ≥ 3600 秒。
- 不要并发启动多个 `collect --holdings` 实例，否则可能在 `holding_security_info` 表上触发死锁。
- 汇总报告已处理跨快照关联：净值和持仓会按 `(institution_code, product_code)` 关联到最新快照，避免新采集日导致覆盖率统计下降。

---

**记录时间**: 2026-06-29  
**更新时间**: 2026-06-30
