# 易方达基金（YFD）数据采集说明

## 机构信息

| 项目 | 内容 |
|------|------|
| 机构名称 | 易方达基金 |
| 机构代码 | YFD |
| 机构类型 | 公募基金公司 |
| 官方网站 | https://www.efunds.com.cn |

## 数据源

采用**天天基金网（Eastmoney）**公开基金列表接口，避免直接爬取基金公司官网。

- **接口地址**：`http://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx`
- **请求方法**：GET
- **是否需要登录**：否
- **是否需要签名**：否

## 请求示例

```http
GET http://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx?t=1&lx=1&letter=&gsid=80000229&text=&sort=zdf,desc&page=1,9999&dt=1463790518010&atfc=%2526onlySale=0
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `t=1` | 固定参数 |
| `lx=1` | 固定参数 |
| `gsid=80000229` | 易方达基金在天天基金网的公司 ID（gsid） |
| `sort=zdf,desc` | 按涨跌幅降序 |
| `page=1,9999` | 分页，获取第 1 页，每页 9999 条 |
| `dt=1463790518010` | 固定时间戳参数 |
| `atfc` | 固定编码 |

## 响应格式

返回 JavaScript 对象字面量，前缀为 `var db=`，需用 `json5` 解析。

```javascript
var db={chars:[...], datas:[["001437","易方达瑞享混合I","YFDRXHHI","","","14.5711","14.5711","","",...], ...]}
```

### 字段映射

| 响应索引 | 字段含义 | 统一 schema 字段 |
|----------|----------|------------------|
| `[0]` | 基金代码 | `product_code` |
| `[1]` | 基金名称 | `product_name` |
| `[2]` | 拼音缩写 | `product_sub_type` |
| `[5]` | 单位净值 | `unit_nav` |
| `[6]` | 累计净值 | `cumulative_nav` |
| `[7]` | 日涨跌幅 | `daily_return`（当前常为空） |
| `[10]` | 近 1 月收益 | `return_1m` |
| `[11]` | 近 3 月收益 | `return_3m` |
| `[12]` | 近 6 月收益 | `return_6m` |
| `[13]` | 近 1 年收益 | `return_1y` |

## 实现文件

- 采集器：`src/fundseeker/collectors/efunds.py`
- 通用基类：`src/fundseeker/collectors/fund_company.py`
- 运行脚本：`scripts/run_fund_company.py YFD`

## 反爬与频率控制

- 请求间隔：5–10 秒随机延迟
- 最大重试：3 次，指数退避
- 默认遵守 robots.txt

## 注意事项

1. Eastmoney 返回的是 JavaScript 对象字面量，不是标准 JSON，需用 `json5` 解析。
2. 不同基金公司的响应格式一致，仅 `gsid` 不同。
3. 日涨跌幅字段可能为空，取决于 Eastmoney 当前返回格式。
