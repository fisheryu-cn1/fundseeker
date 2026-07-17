# 建信理财（JX）数据采集说明

## 机构信息

| 项目 | 内容 |
|------|------|
| 机构名称 | 建信理财 |
| 机构代码 | JX |
| 机构类型 | 银行理财子公司 |
| 官方网站 | https://www.wealthccb.com |

## 数据源

采用建信理财官网公开的 REST API，直接返回 JSON，无需浏览器渲染。

- **接口地址**：`https://www.wealthccb.com/webqueryapp/product/list`
- **请求方法**：POST
- **Content-Type**：`application/json;charset=UTF-8`
- **是否需要登录**：否
- **是否需要签名**：否

## 请求示例

```http
POST https://www.wealthccb.com/webqueryapp/product/list
Content-Type: application/json;charset=UTF-8

{"page": 1, "pageSize": 5000}
```

## 响应格式

```json
{
  "success": true,
  "msg": "",
  "data": {
    "list": [
      {
        "ivsmpdEcd": "产品代码",
        "fndNm": "产品名称",
        "accFxMrgnNetval": "1.0234",
        "drivDt": "2026-06-28",
        "opdt": "2024-01-15",
        "exdt": "2027-01-15",
        "csdcFndRskGrdCd": "R2",
        "fndIvsDrcCd": "001",
        "fndPerfcmprbssAmt": "业绩比较基准",
        "pertxnNumLwrlmtVal": "10000"
      }
    ]
  }
}
```

### 字段映射

| 响应字段 | 字段含义 | 统一 schema 字段 |
|----------|----------|------------------|
| `ivsmpdEcd` | 产品代码 | `product_code` / `registration_code` |
| `fndNm` | 产品名称 | `product_name` |
| `accFxMrgnNetval` | 累计净值 | `unit_nav` / `cumulative_nav` |
| `drivDt` | 净值日期 | `nav_date` |
| `opdt` | 成立日期 | `establish_date` |
| `exdt` | 到期日期 | `maturity_date` |
| `csdcFndRskGrdCd` | 风险等级代码 | `risk_level` |
| `fndIvsDrcCd` | 投资方向代码 | `product_sub_type` |
| `fndPerfcmprbssAmt` | 业绩比较基准 | `performance_benchmark` |
| `pertxnNumLwrlmtVal` | 起购金额 | `min_purchase_amount` |

### 投资方向代码

| `fndIvsDrcCd` | 含义 |
|---------------|------|
| `001` | 固定收益类 |
| `002` | 权益类 |
| `003` | 混合类 |
| `004` | 商品及金融衍生品类 |
| `005` | 货币类 |

## 实现文件

- 采集器：`src/fundseeker/collectors/ccbwm.py`
- 运行脚本：`scripts/run_bank_wm.py JX`

## 反爬与频率控制

- 请求间隔：8–15 秒随机延迟
- 最大重试：3 次

## 注意事项

1. 该接口一次性返回全部产品，无需分页。
2. 风险等级字段来自监管登记数据，较为完整。
3. 部分早期产品可能缺失净值字段。
