# 中银理财（BOC）数据采集说明

## 机构信息

| 项目 | 内容 |
|------|------|
| 机构名称 | 中银理财 |
| 机构代码 | BOC |
| 机构类型 | 银行理财子公司 |
| 官方网站 | https://www.bocwm.cn |

## 数据源

采用中银理财官网公开的 REST API。

- **接口地址**：`https://www.bocwm.cn/webApi/cms/product/queryStaticProducts`
- **请求方法**：POST
- **Content-Type**：`application/json`
- **是否需要登录**：否
- **是否需要签名**：否（固定 `X-CSRF-TOKEN: csrfToken`）

## 请求示例

```http
POST https://www.bocwm.cn/webApi/cms/product/queryStaticProducts
Content-Type: application/json
X-CSRF-TOKEN: csrfToken
X-Requested-With: XMLHttpRequest
Referer: https://www.bocwm.cn/html/1//151/222/index.html

{
  "style": "",
  "timeLimit": "",
  "riskLevel": "",
  "currency": "",
  "productTypeName": "",
  "productClass": [],
  "investorRange": "机构产品",
  "productKeyword": "",
  "pageNo": 1,
  "pageSize": 2000
}
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `style` | 产品形态（空字符串表示全部） |
| `timeLimit` | 产品期限 |
| `riskLevel` | 风险等级 |
| `currency` | 币种 |
| `productTypeName` | 产品投资性质 |
| `productClass` | 产品状态，数组类型，传 `[]` 表示全部 |
| `investorRange` | 投资者范围，如 `"机构产品"` / `"个人产品"` |
| `productKeyword` | 搜索关键词 |
| `pageNo` | 页码 |
| `pageSize` | 每页条数 |

## 响应格式

```json
{
  "result": true,
  "code": 200,
  "data": {
    "total": 825,
    "rows": [
      {
        "productCode": "WFZQ2026072",
        "productName": "（对公专属）中银理财-稳富固收增强优加封闭式2026年072期",
        "startsPrice": 1,
        "riskLevel": "R2中低风险",
        "shareNetWorth": "1.023456",
        "cumulativeNetWorth": null,
        "releaseDate": "2026-06-28",
        "productDetailUrl": "/3/12345.html"
      }
    ]
  }
}
```

### 字段映射

| 响应字段 | 字段含义 | 统一 schema 字段 |
|----------|----------|------------------|
| `productCode` | 产品代码 | `product_code` / `registration_code` |
| `productName` | 产品名称 | `product_name` |
| `shareNetWorth` | 单位净值 | `unit_nav` |
| `cumulativeNetWorth` | 累计净值 | `cumulative_nav` |
| `releaseDate` | 净值日期 | `nav_date` |
| `riskLevel` | 风险等级文本 | `risk_level` |
| `startsPrice` | 起购金额 | `min_purchase_amount` |

## 实现文件

- 采集器：`src/fundseeker/collectors/bocwm.py`
- 运行脚本：`scripts/run_bank_wm.py BOC`

## 反爬与频率控制

- 请求间隔：8–15 秒随机延迟
- 最大重试：3 次

## 注意事项

1. `productClass` 必须传数组类型，传空字符串会报 `HttpMessageNotReadableException`。
2. `investorRange` 传 `"机构产品"` 可获取机构产品；传 `"个人产品"` 获取个人产品。
3. 当前实现默认采集机构产品，如需全量可分别调用个人和机构后去重。
