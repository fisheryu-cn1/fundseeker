# Eastmoney 天天基金 F10 持仓数据

## 数据源概述

- **来源**: 东方财富 / 天天基金网 (fundf10.eastmoney.com)
- **数据类型**: 公募基金持仓明细、行业配置、债券持仓、资产配置
- **覆盖范围**: 全市场公募基金（需已知基金代码）
- **更新频率**: 季度披露（年报/半年报披露完整持仓，季报披露前十大重仓）
- **采集方式**: HTTP API，无需登录或签名

## 接口说明

### 1. 股票持仓（前十大重仓股）

**URL**: `https://fundf10.eastmoney.com/FundArchivesDatas.aspx`

**参数**:

| 参数 | 说明 |
|------|------|
| `type=jjcc` | 基金持仓 |
| `code` | 基金代码，如 `000001` |
| `topline=10` | 返回前十大持仓 |
| `year` | 年份，如 `2024` |

**示例**:

```text
https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code=000001&topline=10&year=2024
```

**返回**: 拼接了四个季度持仓表格的 HTML 片段，每个季度包含：

- 序号
- 股票代码
- 股票名称
- 占净值比例
- 持股数（万股）
- 持仓市值（万元）
- 报告截止日

### 2. 行业配置

**参数**: `type=hytz`

返回基金行业配置占比。

### 3. 债券持仓

**参数**: `type=zqcc`

返回基金债券持仓明细。

### 4. 资产配置

**参数**: `type=zcpz`

返回股票、债券、现金等大类资产配置比例。

## 采集器设计

### 文件位置

- 基类: `src/fundseeker/collectors/holding_base.py`
- 实现: `src/fundseeker/collectors/eastmoney_holding.py`
- 运行脚本: `scripts/run_holding_collection.py`

### 核心逻辑

1. **输入**: 已采集的基金产品代码（来自 `product_info` 表）。
2. **按年份请求**: 一次请求获取该基金某一年四个季度的前十大股票持仓。
3. **表格解析**: 按季度标题拆分 HTML，逐行解析持仓记录。
4. **列自适应**: 由于不同年份表格列数可能变化（如 2026 年新增"变动详情"列），通过内容识别：
   - 包含 `%` 的列为"占净值比例"
   - 最大数值列为"持仓市值"
   - 次大数值列为"持股数"
5. **市场推断**: 根据股票代码前缀推断 A 股市场（上海/深圳/北京）。
6. **输出**: 标准化持仓记录、资产配置汇总、集中度指标。

## 数据库表结构

### holding_report

记录每个产品的每个报告期。

| 字段 | 说明 |
|------|------|
| `product_id` | 关联 product_info.id |
| `report_date` | 报告期截止日 |
| `report_type` | quarterly / annual / interim |
| `report_period` | 可读描述，如"2024年4季度股票投资明细" |
| `data_source` | 数据来源 URL |

### product_holding

持仓明细。

| 字段 | 说明 |
|------|------|
| `report_id` | 关联 holding_report.id |
| `product_id` | 关联 product_info.id |
| `report_date` | 报告期截止日 |
| `asset_code` | 股票/债券代码 |
| `asset_name` | 资产名称 |
| `asset_type` | 资产类型: stock/bond/fund/cash/derivative/other |
| `sub_type` | 子类型: A股/港股/国债/企业债等 |
| `market` | 市场: SH/SZ/HK/US 等 |
| `weight` | 占净值比例（小数） |
| `market_value` | 持仓市值 |
| `share_quantity` | 持股数 |
| `is_top10` | 是否前十大持仓 |
| `sort_order` | 持仓排名 |
| `raw_data` | 原始数据 JSON |

### product_asset_allocation

大类资产配置。

| 字段 | 说明 |
|------|------|
| `report_id` | 关联 holding_report.id |
| `asset_class` | 资产类别: stock/bond/cash/fund/derivative/non_standard/other |
| `weight` | 占比 |
| `market_value` | 市值 |

### product_holding_summary

持仓汇总指标。

| 字段 | 说明 |
|------|------|
| `top10_weight` | 前十大持仓占比 |
| `stock_weight` | 股票占比 |
| `bond_weight` | 债券占比 |
| `cash_weight` | 现金占比 |
| `concentration_score` | 集中度得分（HHI） |
| `holding_count` | 披露持仓数量 |

### holding_security_info

证券基础信息维度表。

| 字段 | 说明 |
|------|------|
| `asset_code` | 证券代码 |
| `market` | 市场 |
| `asset_name` | 证券名称 |
| `asset_type` | 类型 |
| `industry_name` | 行业 |
| `issuer_name` | 发行人 |

## 使用方法

### 采集全部基金产品持仓

```bash
cd /home/cc/projects/fundseeker
source .venv/bin/activate
PYTHONPATH=src python scripts/run_holding_collection.py
```

### 仅采集某个机构

```bash
PYTHONPATH=src python scripts/run_holding_collection.py --code GF
```

### 限制数量并指定历史年份

```bash
PYTHONPATH=src python scripts/run_holding_collection.py --code GF --limit 50 --years 2
```

## 注意事项

1. **债券型基金可能无股票持仓**：天天基金 `jjcc` 接口返回股票持仓，纯债基金可能没有数据，脚本会自动跳过。
2. **季度披露滞后**：基金季报通常在季度结束后 15 个工作日内披露。
3. **列格式变化**：不同年份 HTML 表格列数可能变化，采集器已做自适应解析。
4. **请求频率**：Eastmoney F10 接口较稳定，采集器已设置 0.5-1.5 秒 polite delay。
5. **数据完整性**：前十大重仓仅覆盖最重要的持仓；如需完整持仓，需解析基金定期报告 PDF（巨潮资讯网）。

## 扩展方向

1. **行业配置采集**：实现 `type=hytz` 解析，补充 `product_asset_allocation` 中行业维度。
2. **债券持仓采集**：实现 `type=zqcc` 解析，补充债券型产品持仓。
3. **资产配置采集**：实现 `type=zcpz` 解析，获取股票/债券/现金大类配置。
4. **银行理财产品持仓**：对接中国理财网产品公告 / 投资报告 PDF 解析。
5. **完整持仓解析**：从巨潮资讯网下载基金季报/半年报/年报 PDF，解析完整股票/债券持仓。
