# 浦银理财（SPD）数据采集说明

## 机构信息

| 项目 | 内容 |
|------|------|
| 机构名称 | 浦银理财 |
| 机构代码 | SPD |
| 机构类型 | 银行理财子公司 |
| 官方网站 | https://www.spdb-wm.com |

## 数据源

采用浦银理财官网公开的 REST API。

- **接口地址**：`https://www.spdb-wm.com/api/search`
- **请求方法**：POST
- **Content-Type**：`application/json`
- **是否需要登录**：否
- **是否需要签名**：否

## 请求示例

### 产品列表

```http
POST https://www.spdb-wm.com/api/search
Content-Type: application/json

{
  "chlid": 1002,
  "cutsize": 150,
  "dynexpr": [],
  "dynidx": 1,
  "extopt": [],
  "orderby": "",
  "page": 1,
  "size": 99999,
  "searchword": ""
}
```

### 最新净值

```http
POST https://www.spdb-wm.com/api/search
Content-Type: application/json

{
  "chlid": 1006,
  "cutsize": 150,
  "dynexpr": [],
  "dynidx": 1,
  "extopt": [],
  "orderby": "",
  "page": 1,
  "size": 99999,
  "searchword": ""
}
```

### 参数说明

| 参数 | 说明 |
|------|------|
| `chlid` | 数据频道：`1002`=产品列表，`1006`=最新净值，`1003`=历史净值 |
| `page` | 页码 |
| `size` | 每页条数，可设较大值一次性拉取 |
| `searchword` | 筛选条件，如 `"(RISK_GRADE='较低风险')"` |

## 响应格式

```json
{
  "code": 20000,
  "message": "success",
  "data": {
    "totalElements": 7943,
    "totalPages": 1,
    "content": [
      {
        "PRDC_CD": "2301260136",
        "PRDC_NM": "悦享利封闭式888号（邀新专属）",
        "PRDC_FRM": "封闭式净值型",
        "RISK_GRADE": "较低风险",
        "PRDC_TYP": "固定收益类",
        "PRDC_STT": "存续",
        "SLL_OBJC": "对私",
        "TERM_TYPE": "1-3年(含)",
        "PRDC_RGST_CD": "Z7006926000231",
        "ACCT_DT": "2026-06-28"
      }
    ]
  }
}
```

### 字段映射（产品列表 chlid=1002）

| 响应字段 | 字段含义 | 统一 schema 字段 |
|----------|----------|------------------|
| `PRDC_CD` | 产品代码 | `product_code` |
| `PRDC_NM` | 产品名称 | `product_name` |
| `PRDC_FRM` | 产品形态 | `product_sub_type` |
| `RISK_GRADE` | 风险等级 | `risk_level` |
| `PRDC_TYP` | 产品类型 | `product_type` |
| `PRDC_STT` | 产品状态 | `status` |
| `SLL_OBJC` | 销售对象 | - |
| `TERM_TYPE` | 期限类型 | - |
| `PRDC_RGST_CD` | 登记编码 | `registration_code` |

### 字段映射（净值 chlid=1006）

| 响应字段 | 字段含义 |
|----------|----------|
| `REAL_PRD_CODE` | 产品代码，对应 `PRDC_CD` |
| `NAV` | 份额净值 |
| `TOT_NAV` | 累计净值 |
| `ISS_DATE` | 净值日期 |

## SSL/TLS 兼容性

浦银理财服务器不支持 secure renegotiation，OpenSSL 3 环境下需要给 `requests` 配置 `OP_LEGACY_SERVER_CONNECT`。已在 `PoliteHttpClient` 中新增 `ssl_legacy` 参数支持。

## 实现文件

- 采集器：待实现 `src/fundseeker/collectors/spdbwm.py`
- HTTP 客户端：`src/fundseeker/utils/http.py`
- 运行脚本：`scripts/run_bank_wm.py SPD`

## 反爬与频率控制

- 请求间隔：8–15 秒随机延迟
- 最大重试：3 次

## 注意事项

1. 产品列表和最新净值需要分两次请求，按 `PRDC_CD == REAL_PRD_CODE` 关联。
2. 列表接口可能返回母产品和子产品，如需产品级去重需参考前端过滤逻辑。
3. 请求速度快，但仍建议控制频率。
