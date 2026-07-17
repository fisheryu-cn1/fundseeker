# 光大理财（CEB）数据采集说明

## 机构信息

| 项目 | 内容 |
|------|------|
| 机构名称 | 光大理财 |
| 机构代码 | CEB |
| 机构类型 | 银行理财子公司 |
| 官方网站 | https://www.cebwm.com |

## 数据源选择

光大理财的数据源相对复杂，目前调研了多个渠道：

| 数据源 | 可行性 | 备注 |
|--------|--------|------|
| 光大理财官网 `cebwm.com` | ❌ | 有瑞数/WAF 保护，requests 无法获取 |
| 光大银行官网 `cebbank.com` | ⚠️ | 可获取公告列表，但详情多为 PDF，解析成本高 |
| 中国理财网 `chinawealth.com.cn` | ✅ | 权威、全面，但完整 API 需加密或 Playwright |

**推荐方案**：使用 **中国理财网** 作为数据源，通过 **Playwright** 操作筛选页面获取光大理财全量产品列表。

## 方案一：中国理财网 Playwright 采集（推荐）

### 页面地址

`https://www.chinawealth.com.cn/lcweb/management/proScreen`

### 采集步骤

1. 打开中国理财网产品筛选页面。
2. 在"发行机构"筛选框中输入"光大理财"。
3. 勾选"光大理财有限责任公司"。
4. 点击"确定"，触发产品列表加载。
5. 解析渲染后的产品表格，提取字段。
6. 如需翻页，点击分页按钮继续采集。

### 页面 API（供参考）

Playwright 运行时可观察到以下加密 API：

- `POST https://www.chinawealth.com.cn/lcw-fe-service/m/n` — RSA 密钥交换
- `POST https://www.chinawealth.com.cn/lcw-fe-service/prod/search` — 加密后的产品搜索

响应体为密文，需 AES 解密。因此**推荐直接解析 DOM**，而非解密 API。

### 可获取字段

页面表格通常包含：

- 产品名称
- 产品登记编码
- 发行机构
- 产品风险等级
- 运作模式
- 募集方式
- 期限类型
- 投资性质

**净值数据**需进入产品详情页获取。

## 方案二：中国理财网加密 API（高级）

### 加密流程

1. 前端生成 1024 位 RSA 密钥对。
2. `POST /lcw-fe-service/m/n` 上传 public key，服务端返回 RSA 加密后的 AES 密钥。
3. 用本地私钥解密得到 `manageKey`。
4. 后续请求：`AES 加密 body`，并附加：
   - `X-Nonce`：10 位随机字符串
   - `X-Timestamp`：当前时间戳
   - `X-Sign`：HMAC 签名

### 复杂度

高。需要在前端 JS 中定位加密函数并逆向实现，维护成本较高。

## 实现文件

- 采集器：待实现 `src/fundseeker/collectors/cebwm.py`
- 运行脚本：待支持 `scripts/run_bank_wm.py CEB`

## 反爬与频率控制

- 页面加载等待：5–10 秒
- 翻页间隔：5–8 秒
- 建议单会话不要高频翻页

## 注意事项

1. 光大理财官网和光大银行官网均有较强的反爬/WAF，不建议直接 requests。
2. 中国理财网数据权威，但页面为 Vue SPA，需等待渲染完成。
3. 如只需少量代表性产品，可关注中国理财网首页推荐位（但当前静态 JSON 路径可能已变更）。
4. SSL：光大银行/光大理财站点使用旧版 TLS 协商，OpenSSL 3.x 需开启 `UnsafeLegacyRenegotiation`。
