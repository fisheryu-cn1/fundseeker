# 信银理财（CITIC）数据采集说明

## 机构信息

| 项目 | 内容 |
|------|------|
| 机构名称 | 信银理财 |
| 机构代码 | CITIC |
| 机构类型 | 银行理财子公司 |
| 官方网站 | https://www.citic-wealth.com |

## 数据源

采用信银理财官网公开的 REST API，无需登录和签名。

- **接口地址**：`https://wechat.citic-wealth.com/cms.product/api/custom/productInfo/fundList`
- **请求方法**：GET
- **是否需要登录**：否
- **是否需要签名**：否

## 请求示例

```http
GET https://wechat.citic-wealth.com/cms.product/api/custom/productInfo/fundList?pageNum=1&pageSize=200&productType=2&prodSaleCustom=0
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `pageNum` | 页码，从 1 开始 |
| `pageSize` | 每页条数，建议 200 |
| `productType` | 产品类型：`1`=募集期，`2`=每日购，`3`=定开，`4`=货币，`5`=封闭 |
| `prodSaleCustom` | 销售对象：`0`=个人，`1`=机构 |
| `riskLevel` | 可选，风险等级 `1~5` 对应 PR1~PR5 |
| `distributorCode` | 可选，销售渠道代码 |

## 响应格式

```json
{
  "code": "0000",
  "msg": "获取成功",
  "data": {
    "records": [
      {
        "prodCode": "AF245689D",
        "prodName": "信银理财安盈象固收稳健七天持有期1号",
        "prodNameShort": "安盈象固收稳健七天持有期1号",
        "riskLevel": 2,
        "riskLevelStr": "PR2-中低风险",
        "nav": 1.0234,
        "navStr": "1.0234",
        "totalNav": 1.0456,
        "totalNavStr": "1.0456",
        "navDate": "2026-06-28",
        "navDateStr": "2026-06-28",
        "benchmarks": "业绩比较基准",
        "raiseTypeStr": "公募",
        "profitTypeStr": "净值型",
        "respProductTypeStr": "每日购",
        "establishDateStr": "2024-01-15",
        "minSubsP": 1,
        "minApplyP": 1
      }
    ],
    "total": 2781,
    "size": 200,
    "current": 1,
    "pages": 14
  }
}
```

### 字段映射

| 响应字段 | 字段含义 | 统一 schema 字段 |
|----------|----------|------------------|
| `prodCode` | 产品代码 | `product_code` |
| `prodName` | 产品名称 | `product_name` |
| `prodNameShort` | 产品简称 | `product_short_name` |
| `riskLevel` / `riskLevelStr` | 风险等级 | `risk_level` |
| `nav` / `navStr` | 单位净值 | `unit_nav` |
| `totalNav` / `totalNavStr` | 累计净值 | `cumulative_nav` |
| `navDate` / `navDateStr` | 净值日期 | `nav_date` |
| `benchmarks` | 业绩比较基准 | `performance_benchmark` |
| `raiseTypeStr` | 募集方式 | - |
| `profitTypeStr` | 产品类型 | `product_type` |
| `respProductTypeStr` | 运作形态 | `product_sub_type` |
| `establishDateStr` | 成立日 | `establish_date` |
| `minSubsP` | 起购金额 | `min_purchase_amount` |
| `minApplyP` | 追加金额 | `min_additional_amount` |

## SSL/TLS 兼容性

`wechat.citic-wealth.com` 服务端使用 unsafe legacy renegotiation，OpenSSL 3 环境下需要给 `requests` 配置 `OP_LEGACY_SERVER_CONNECT`。已在 `PoliteHttpClient` 中新增 `ssl_legacy` 参数支持。

## 实现文件

- 采集器：待实现 `src/fundseeker/collectors/citicwm.py`
- HTTP 客户端：`src/fundseeker/utils/http.py`
- 运行脚本：`scripts/run_bank_wm.py CITIC`

## 反爬与频率控制

- 请求间隔：8–15 秒随机延迟
- 最大重试：3 次
- 建议单类请求间隔不低于 5 秒

## 注意事项

1. 同一产品可能同时出现在个人/机构或多个 `productType` 分类中，建议以 `prodCode` 去重。
2. 全量采集需要遍历 `productType=1,2,3,4,5` 和 `prodSaleCustom=0,1`，但实际以个人每日购为主即可覆盖大部分产品。
