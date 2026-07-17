# FundSeeker

理财产品数据采集、持仓相似性分析与聚类展示系统。

## 项目简介

FundSeeker 用于自动采集公募基金公司、银行理财子公司等机构的理财产品信息（产品列表、净值、收益率、持仓、行情等），并基于持仓特征对产品进行相似性聚类、Brinson 归因与可视化展示，辅助分析不同投资方向、不同基金经理的微观操作能力差异。

## 主要能力

- **数据采集**：产品列表、净值、收益率、公告、费率、市场行情、季度持仓等；
- **持仓相似性分析**：基于个股权重或行业权重特征进行 K-Means 聚类；
- **增量聚类（v1.01）**：支持全量/增量两种计算模式，监控 silhouette/inertia 等指标劣化时自动回退全量；
- **Brinson 归因**：对比簇内产品与簇平均或指数基准的超额收益来源；
- **Web 展示**：Flask 只读查询界面与聚类结果展示；
- **CLI 工具**：采集、查询、聚类、归因独立 CLI，便于 agent / cron 调度。

## 目录结构

```
.
├── archive/v1.0/          # v1.0 版本历史存档（代码、文档、报告）
├── config/                # 机构配置等
├── docs/                  # 设计文档、使用说明、评审报告（v1.01 及当前版本）
├── docs/ver1.0/           # v1.0 版本文档归档
├── Proposal/              # 初期提案与数据源规范
├── reports/               # 生成的静态报告
├── scripts/               # 可执行脚本与 CLI 入口
│   ├── fundseeker_cli.py              # 数据采集 CLI
│   ├── fundseeker_query.py            # 只读查询 CLI
│   ├── fundseeker_similarity.py       # 持仓相似性分析 CLI（官方入口）
│   ├── fundseeker_similarity_cron.sh  # 相似性分析 cron 脚本
│   └── fundseeker_cron.sh             # 数据采集 cron 脚本
├── src/fundseeker/        # 核心源码
│   ├── cleaners/          # 数据清洗
│   ├── collectors/        # 数据采集器
│   ├── models/            # SQLAlchemy 数据模型
│   ├── similarity/        # 聚类、归因、特征工程（v1.01 核心）
│   ├── utils/             # 通用工具
│   └── web/               # Flask Web UI
└── tests/                 # 测试用例
```

## 环境要求

- Python 3.10+
- PostgreSQL
- Linux（cron 脚本依赖 bash）

## 快速开始

1. 安装依赖：

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. 初始化数据库：

   ```bash
   PYTHONPATH=src python scripts/fundseeker_cli.py init-db
   ```

3. 执行数据采集：

   ```bash
   PYTHONPATH=src python scripts/fundseeker_cli.py collect --all
   ```

4. 执行持仓相似性分析：

   ```bash
   # 首次或季度披露后执行全量聚类
   PYTHONPATH=src python scripts/fundseeker_similarity.py pipeline \
       --start-date 2026-04-01 --end-date today \
       --mode full --k auto
   ```

5. 启动 Web UI：

   ```bash
   PYTHONPATH=src python scripts/run_web.py
   ```

   默认访问 `http://127.0.0.1:5001`。

## 定时调度

项目提供两个独立的 cron 脚本，分别对应数据采集与相似性分析：

- `scripts/fundseeker_cron.sh`：每日信息采集；
- `scripts/fundseeker_similarity_cron.sh`：每日/季度相似性分析跑批。

OpenClaw 配置示例参见 `docs/openclaw-scheduling-guide-v1.01.md`。

## 文档索引

| 文档 | 路径 |
|---|---|
| v1.01 CLI 改进设计方案 | `docs/fundseeker-similarity-cli-1.01-改进设计方案.md` |
| v1.01 CLI 使用说明 | `docs/fundseeker-similarity-cli-v1.01.md` |
| v1.01 OpenClaw 调度指南 | `docs/openclaw-scheduling-guide-v1.01.md` |
| v1.01 增量聚类设计方案 | `docs/持仓相似性量化评估-1.01-增量聚类设计方案.md` |
| v1.01 增量聚类评审报告 | `docs/持仓相似性量化评估-1.01-增量聚类评审报告.md` |
| v1.01 增量聚类修复评审报告 | `docs/持仓相似性量化评估-1.01-增量聚类修复评审报告.md` |
| v1.01 CLI 与调度评审报告 | `docs/持仓相似性-CLI与调度-v1.01-评审报告.md` |
| v1.0 完整设计方案 | `docs/ver1.0/持仓相似性量化评估完整设计方案-v1.0.md` |
| v1.0 前端展示设计说明 | `docs/ver1.0/前端展示设计说明-v1.0.md` |
| v1.0 数据库设计说明 | `docs/ver1.0/数据库设计说明-v1.0.md` |

## 测试

```bash
PYTHONPATH=src .venv/bin/pytest tests/ -q
```

## 注意事项

- `.venv/`、`.claude/`、`.agents/`、`skills-lock.json`、缓存目录等属于本地环境文件，已加入 `.gitignore`，不应提交到仓库。
- 请确保数据库连接配置正确。默认使用 `src/fundseeker/models/database.py` 中的通用占位符；本地真实连接可写入 `src/fundseeker/models/database_local.py`（已加入 `.gitignore`，不会提交），或通过环境变量 `FUNDSEEKER_DATABASE_URL` 覆盖。
