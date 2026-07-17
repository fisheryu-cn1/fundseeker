# 汇添富基金（HTF）数据采集说明

## 机构信息

| 项目 | 内容 |
|------|------|
| 机构名称 | 汇添富基金 |
| 机构代码 | HTF |
| 机构类型 | 公募基金公司 |
| 官方网站 | https://www.99fund.com |

## 数据源

采用**天天基金网（Eastmoney）**公开基金列表接口。

- **接口地址**：`http://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx`
- **请求方法**：GET
- **是否需要登录**：否
- **是否需要签名**：否

## 请求示例

```http
GET http://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx?t=1&lx=1&letter=&gsid=80053708&text=&sort=zdf,desc&page=1,9999&dt=1463790518010&atfc=%2526onlySale=0
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `gsid=80053708` | 汇添富基金在天天基金网的公司 ID |

其他参数与易方达基金相同，参见 [YFD-易方达基金.md](./YFD-易方达基金.md)。

## 响应格式

同易方达基金，返回 `var db=...` 形式的 JavaScript 对象字面量。

## 实现文件

- 采集器：`src/fundseeker/collectors/htfund.py`
- 通用基类：`src/fundseeker/collectors/fund_company.py`
- 运行脚本：`scripts/run_fund_company.py HTF`

## 反爬与频率控制

- 请求间隔：5–10 秒随机延迟
- 最大重试：3 次

## 注意事项

1. 与易方达共享同一套 `FundCompanyCollector` 基类。
2. 净值字段索引为 `[5]`（单位净值）和 `[6]`（累计净值）。
