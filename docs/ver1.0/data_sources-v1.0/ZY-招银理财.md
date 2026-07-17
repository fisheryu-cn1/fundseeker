# 招银理财（ZY）数据采集说明

## 机构信息

| 项目 | 内容 |
|------|------|
| 机构名称 | 招银理财 |
| 机构代码 | ZY |
| 机构类型 | 银行理财子公司 |
| 官方网站 | https://www.cmbchinawm.com |

## 数据源

招银理财官网直接访问受限（403），因此采用**招商银行代销页面**作为数据源。该页面使用 React/umi 前端框架，API 请求带有动态签名（`timespan` / `signature`），直接构造 HTTP 请求困难，故使用 **Playwright** 拦截浏览器发出的 API 响应。

- **页面地址**：`https://cfweb.paas.cmbchina.com/corporate/ProdBySeries?code=020186`
- **拦截接口**：包含 `getProductByFilterByPage` 的 XHR 响应
- **是否需要登录**：否
- **是否需要签名**：由页面 JS 自动生成，Playwright 复用

## Playwright 采集流程

1. 启动 Chromium 无头浏览器。
2. 监听 `response` 事件，过滤 URL 包含 `getProductByFilterByPage` 的响应。
3. 访问招商银行代销页面。
4. 点击"查看更多"展开系列列表。
5. 依次点击"招银理财"系列链接，触发产品加载。
6. 从拦截到的响应体中提取产品列表。
7. 按产品代码去重。

### 响应体结构

```json
{
  "body": {
    "data": [
      {
        "prdCode": "产品代码",
        "prdName": "产品名称",
        "netValue": "1.0234",
        "beginDate": "2024-01-15",
        "expireDate": "2027-01-15",
        "risk": "R2中低风险",
        "rateDes": "业绩比较基准",
        "initMoney": "10000",
        "style": "固定收益类",
        "regCode": "登记编码"
      }
    ]
  }
}
```

### 字段映射

| 响应字段 | 字段含义 | 统一 schema 字段 |
|----------|----------|------------------|
| `prdCode` | 产品代码 | `product_code` |
| `prdName` | 产品名称 | `product_name` |
| `netValue` | 单位净值 | `unit_nav` |
| `beginDate` | 成立日 | `establish_date` |
| `expireDate` | 到期日 | `maturity_date` |
| `risk` | 风险等级文本 | `risk_level` |
| `rateDes` | 业绩比较基准 | `performance_benchmark` |
| `initMoney` | 起购金额 | `min_purchase_amount` |
| `style` | 产品类型 | `product_sub_type` |
| `regCode` | 登记编码 | `registration_code` |

## 实现文件

- 采集器：`src/fundseeker/collectors/cmbwm.py`
- 运行脚本：`scripts/run_bank_wm.py ZY`
- 配置项：`config/institutions.yaml` 中的 `cmbwm.max_series` 和 `cmbwm.wait_seconds`

## 反爬与频率控制

- 页面加载等待：3–5 秒
- 系列切换等待：由 `cmbwm.wait_seconds` 控制，默认 3 秒
- 最大遍历系列数：由 `cmbwm.max_series` 控制，默认 3

## 注意事项

1. 当前仅遍历前 N 个系列，完整覆盖需要增大 `max_series` 或反向破解签名算法。
2. 签名机制复杂，不建议直接用 requests 构造请求。
3. 响应体为 `body.data`，注意与常见的 `data` 字段区分。
