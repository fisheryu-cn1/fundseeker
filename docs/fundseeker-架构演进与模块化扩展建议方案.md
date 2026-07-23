# FundSeeker 架构演进与模块化扩展建议方案

> 版本：建议稿（面向 v1.02+）
> 依据文档：
> - `docs/多期持仓变化分析建议.md`（多期持仓变化分析维度与优先级）
> - `docs/多期持仓数据下的聚类分析展示需求建议.md`（多期聚类展示方案）
> - `docs/fundseeker-similarity-cli-v1.01.md` 与 `docs/fundseeker-similarity-cli-1.01-改进设计方案.md`（v1.01 系统现状）
>
> 目标：回答三个问题——
> 1. 整体架构如何具备灵活的可扩展性与模块解耦，以承接"大模型对话式分析"和更多数据分析方法；
> 2. 随着数据积累，分析方法如何做到既方便扩展、又统一管理，避免代码零散；
> 3. 数据和代码复杂以后，如何维持可维护性，尤其是便于 AI Coding 工具做自动化升级维护。

---

## 1. 现状评估

### 1.1 当前架构的合理之处

现有三层管道（采集 → 分析 → 展示，PostgreSQL 为共享存储）是健康的，且已具备若干对扩展非常有利的既有约定：

| 既有约定 | 位置 | 对扩展的价值 |
|---|---|---|
| 采集器注册表模式 | `runner.py` 的 `FUND_COLLECTORS` / `BANK_WM_COLLECTORS` 字典 | 新增数据源 = 写子类 + 注册一行，已是项目惯例 |
| 服务层与 CLI 分离 | `similarity/service.py` + `similarity/cli_core.py` | 业务逻辑不在脚本里，agent/cron 可直接调用 |
| 统一 JSON 输出 | 所有 CLI 子命令 | 天然适合 agent 消费，也是未来 LLM tool 的返回格式 |
| 运行中心（run-centric）结果模型 | `SimilarityClusterRun` 等 `similarity_*` 表 | 同类分析结果可重复运行、可追溯、幂等 |
| DB-free 纯计算测试 | `tests/test_similarity.py` 用内存 `FeatureMatrix` | 计算逻辑可脱离数据库测试，AI 工具易验证改动 |
| agent 引导文档 | `CODEBUDDY.md` | AI Coding 工具的第一手上下文 |

### 1.2 正在积累的结构性问题

两份多期持仓建议文档合计提出了 15+ 个新分析方向（重仓股异动、集中度时序、行业漂移、调仓时机、Brinson 时序、簇演化、风格稳定性……）。如果按当前结构直接落地，会出现以下问题：

| 问题 | 具体表现 | 后果 |
|---|---|---|
| `similarity/` 包职责膨胀 | 已有 13 个模块（service 666 行、cli_core 675 行），新分析与"相似性"并无关系（如调仓时机、风险指标） | 包名误导、边界模糊，新代码无处安放 |
| `web/queries.py` 单体化 | 已 2322 行，所有页面 SQL 堆在一个文件 | 每加一个分析就改同一个巨型文件，冲突与回归风险高 |
| 脚本目录增生 | `scripts/` 已有 14 个脚本，含一次性迁移脚本 | 每类分析一个 CLI 脚本的趋势不可持续 |
| 无分析注册机制 | 新增分析 = 改 service + 改 cli_core + 改 app.py + 改 queries.py，四处手工接线 | 扩展成本高，且接线方式每次不同 |
| 无 LLM 接入点 | 对话式分析若直接读库，需要一套新的数据访问通道 | 容易做成旁路系统，与 CLI/Web 三套口径 |

**核心判断**：问题不在分层，而在"分析能力"这一维度缺少一个统一抽象的扩展点。采集层已有注册表模式，分析层还没有。补上这一层抽象，三个问题（扩展性、统一管理、LLM 接入）可以被同一个机制解决。

---

## 2. 目标架构

### 2.1 总体分层

```
┌─────────────────────────────────────────────────────────────┐
│ 入口层（Entry Points）                                       │
│  scripts/fundseeker_cli.py        数据采集（不变）            │
│  scripts/fundseeker_similarity.py 相似性分析（保留，内部改造）│
│  scripts/fundseeker_analysis.py   【新增】通用分析 CLI        │
│  scripts/run_web.py               Web UI（路由自动注册）      │
│  scripts/fundseeker_assistant.py  【新增】LLM 对话分析        │
├─────────────────────────────────────────────────────────────┤
│ 能力层（Capabilities）                                       │
│  src/fundseeker/collectors/   数据源插件（已有注册表模式）    │
│  src/fundseeker/analysis/     【新增】分析插件注册框架        │
│    ├─ registry.py             注册表 + 自动发现               │
│    ├─ base.py                 AnalysisModule 抽象基类         │
│    ├─ holding_change/         插件：重仓股异动                │
│    ├─ holding_evolution/      插件：集中度/换手率时序         │
│    ├─ cluster_evolution/      插件：多期聚类对比              │
│    ├─ trade_timing/           插件：调仓时机评估              │
│    └─ ...                     后续新增分析均为一个插件目录    │
│  src/fundseeker/similarity/   相似性计算内核（保留）          │
│  src/fundseeker/assistant/    【新增】LLM 对话引擎 + 工具桥   │
├─────────────────────────────────────────────────────────────┤
│ 数据层（Data）                                               │
│  src/fundseeker/models/       表定义（不变）                  │
│  PostgreSQL：raw 表 / similarity_* / 【新增】analysis_*      │
└─────────────────────────────────────────────────────────────┘
```

设计原则：

- **不动数据层和采集层**：它们已经工作良好，重构风险大于收益。
- **`similarity/` 保留为计算内核**：K-Means、Brinson、特征矩阵等纯算法不搬家，避免大爆炸式重写。`analysis/` 下的插件可以**调用** similarity 的函数，正如两份建议文档中"复用 `overlap_coefficient`"的思路。
- **一个扩展点服务三个消费方**：分析插件注册后，CLI、Web、LLM 工具三处自动可用，不重复接线。

### 2.2 分析插件抽象（核心机制）

借鉴采集层 `FUND_COLLECTORS` 的成功经验，定义最小抽象：

```python
# src/fundseeker/analysis/base.py
@dataclass
class AnalysisSpec:
    """分析模块的元数据清单。"""
    name: str                    # 唯一标识，如 "holding_change"
    title: str                   # 展示名，如 "重仓股异动报告"
    description: str             # 一句话说明（供 CLI help / Web 目录 / LLM 工具描述）
    version: str = "1.0"
    required_tables: tuple[str, ...] = ()   # 依赖的表，用于运行前自检
    min_report_periods: int = 1             # 需要至少几期持仓数据
    persist: bool = False                   # 是否落库到 analysis_* 表
    schedule_hint: str | None = None        # 调度建议，如 "quarterly" / "daily"

class AnalysisModule(ABC):
    spec: AnalysisSpec

    @abstractmethod
    def run(self, session, **params) -> dict:
        """执行分析，返回 JSON 可序列化的 dict。与 CLI 输出、API 响应、LLM 工具返回同源。"""
```

注册与发现：

```python
# src/fundseeker/analysis/registry.py
ANALYSES: dict[str, AnalysisModule] = {}

def register(module: AnalysisModule) -> AnalysisModule: ...

def discover() -> None:
    """扫描 analysis/ 下各子包，导入即注册（与 collectors 同风格）。"""
```

**为什么这个抽象足够**：

- `run()` 返回 `dict`，天然同时满足：CLI 的 JSON 输出约定、Flask 的 `jsonify`、LLM function-calling 的工具返回。**同一份结果，三个出口**。
- `spec` 元数据让"统一管理"落地：`analysis list` 列出全部能力及数据就绪度（`min_report_periods` vs 实际报告期数），Web 自动生成能力目录页，LLM 自动获得工具清单和描述。
- 参数走 `**params` + 各插件内部的参数解析函数，CLI 用 argparse 子命令动态生成，不强迫所有分析共用一套参数。

### 2.3 三个消费方如何接入

**CLI（`scripts/fundseeker_analysis.py`）**：

```bash
PYTHONPATH=src python scripts/fundseeker_analysis.py list           # 能力清单 + 数据就绪度
PYTHONPATH=src python scripts/fundseeker_analysis.py list --json
PYTHONPATH=src python scripts/fundseeker_analysis.py run holding_change --product-id 117661
PYTHONPATH=src python scripts/fundseeker_analysis.py run cluster_evolution --start 2026-04-01 --end 2026-07-10
```

子命令由注册表动态生成，新增插件**不需要改 CLI 代码**。

**Web**：`app.py` 增加两个通用路由：

```python
@app.route("/analysis")                      # 能力目录页（自动列出所有插件）
@app.route("/api/analysis/<name>", methods=["POST"])  # 通用执行端点，参数透传
```

有定制页面需求的插件（如 `cluster_evolution` 的 Sankey 对比页）自带模板和专属路由，注册到插件自己的 `web_routes` 钩子；没有定制页面的插件至少自动获得 API 和目录入口。`queries.py` 中属于某插件的查询函数**移入插件目录内的 `queries.py`**，巨型文件按职责拆分。

**LLM 对话（`src/fundseeker/assistant/`）**：

```python
# assistant/tools.py —— 插件注册表即工具目录
def build_tool_manifest() -> list[dict]:
    """把每个 AnalysisModule 转为 LLM function-calling 的 tool 定义：
    name = spec.name, description = spec.description,
    parameters = 插件声明的参数 schema。"""

def dispatch_tool(name: str, arguments: dict) -> dict:
    """LLM 调用工具 → 路由到 ANALYSES[name].run(session, **arguments)。"""
```

**这是本方案的关键协同**：LLM 对话分析不需要单独建设一套数据通道。分析插件注册表就是 LLM 的工具目录——每新增一个分析插件，对话能力自动多一个工具；工具描述、参数说明、返回格式全部复用 `spec` 和 `run()`。这直接回答了"分析方法既要方便扩展、又要统一管理"的问题。

---

## 3. LLM 对话式分析子系统设计

### 3.1 定位与边界

对话式分析是**消费方**，不是新的数据层。约束如下：

| 约束 | 说明 |
|---|---|
| 只读 | LLM 只能调用分析插件和只读查询函数，**绝不生成 SQL**，绝不接触写路径 |
| 工具白名单 | 可调用的能力 = 插件注册表 + 少量显式声明的只读查询工具（产品搜索、持仓查询等），不允许任意代码执行 |
| 结果可溯源 | 对话中引用的数字必须来自某次 `run()` 返回的 dict，回答中携带数据来源（分析名 + 参数 + 报告期） |
| 无状态会话先行 | 第一版只做单轮/有限多轮问答，会话历史不落库；需要持久化时再加 `assistant_session` 表 |

### 3.2 模块结构

```
src/fundseeker/assistant/
├── __init__.py
├── client.py       # LLM API 封装：provider 抽象（OpenAI 兼容协议先行），
│                   #   API key 从环境变量读取，超时/重试复用 utils/http.py 策略
├── tools.py        # 插件注册表 → tool manifest；dispatch_tool 路由
├── context.py      # 系统提示词 + 数据概览摘要（当前报告期、数据覆盖范围），
│                   #   让 LLM 知道"有什么数据可以问"
└── engine.py       # 对话循环：user → LLM → tool calls → 汇总回答
```

### 3.3 与现有约定的对齐

- **配置**：API key 走环境变量（如 `FUNDSEEKER_LLM_API_KEY`），与 `FUNDSEEKER_DATABASE_URL` 同风格，禁止入库入仓。
- **CLI 入口**：`scripts/fundseeker_assistant.py chat`（交互式）和 `chat --once "问题"`（单轮，JSON 输出，供 agent 管道使用）——延续"所有入口输出 JSON"的约定。
- **cron 零 LLM**：维持 `CODEBUDDY.md` 中"调度脚本零 LLM 调用"的原则，LLM 功能只在按需入口出现。
- **降级**：未配置 API key 时入口明确报错退出（退出码 2），不影响系统其他部分。

---

## 4. 分析方法的扩展与统一管理规范

### 4.1 新增一个分析的标准动作（Golden Path）

未来新增任何分析（包括两份建议文档中的全部方向），流程固定为：

1. 新建目录 `src/fundseeker/analysis/<name>/`，内含：
   - `__init__.py`：定义 `AnalysisModule` 子类并 `register()`；
   - `compute.py`：**DB-free 纯计算函数**（输入 DataFrame/dict，输出 dict），供单元测试；
   - `service.py`：会话编排，读库 → 调 compute → （可选）写 `analysis_*` 表；
   - `queries.py`（可选）：该分析的 SQL；
   - `templates/`、`web_routes.py`（可选）：定制展示。
2. 在 `tests/test_<name>.py` 写 DB-free 单元测试（沿用 `test_similarity.py` 的内存数据模式）。
3. 若需落库，在 `models/tables.py` 加 `analysis_<name>_*` 表，遵循 `INSERT ... ON CONFLICT` 幂等约定和唯一约束。
4. 在 `CODEBUDDY.md` 的能力清单中登记一行。

完成后 CLI `list`/`run`、Web 目录/API、LLM 工具**自动可用**，无需任何接线改动。

### 4.2 两份建议文档中的分析如何落位

| 来源 | 分析 | 插件名建议 | 依赖期数 | 优先级（沿用原文档） |
|---|---|---|---|---|
| 多期持仓变化 | 重仓股异动报告 | `holding_change` | 2 | P0 |
| 多期持仓变化 | 集中度与换手率时序 | `holding_evolution` | 2 | P1 |
| 多期持仓变化 | 行业配置漂移 | `industry_drift` | 2 | P1 |
| 多期持仓变化 | 调仓时机判断（结合行情） | `trade_timing` | 2 + quotes | P1（增强） |
| 多期持仓变化 | Brinson 归因时序 | `attribution_timeseries` | 多期 | P2 |
| 多期持仓变化 | 风格标签与异常信号 | `style_drift` | 多期 + 外部数据 | P3 |
| 聚类展示 | 时间区段对齐 + 单期回退 | （并入 `cluster_evolution` 的 resolve 逻辑） | 1 | P0 |
| 聚类展示 | 双期对比（簇映射/成员流动） | `cluster_evolution` | 2 | P0 |
| 聚类展示 | 多期时间轴 | `cluster_evolution`（同插件多模式） | 3+ | P2 |
| 聚类展示 | 单产品归属时间轴/稳定性 | `product_stability` | 多期 | P1 |

`similarity/` 内核被这些插件调用，不重复实现：`cluster_evolution` 复用 `similarity.similarity.overlap_coefficient` 做簇映射，`attribution_timeseries` 复用 `similarity.attribution`，与建议文档的衔接思路一致。

### 4.3 结果表管理约定

- 命名：`analysis_<name>_<entity>`，与 `similarity_*` 前缀惯例一致，一眼区分"原始数据 / 相似性结果 / 通用分析结果"。
- 落库判断标准：**计算贵、需追溯、被多处消费**三者居其二才落库；轻量对比类（如双期簇映射，数据量小）实时计算不落库——这与聚类展示建议文档第 7.3 节的判断一致。
- 需要落库且带批次概念的，沿用 run-centric 模型（`..._run` 主表 + 明细表），与 `SimilarityClusterRun` 同构。
- 迁移脚本继续放 `scripts/migrate_*.py`，命名带版本号，一次性脚本执行后在文件头标注执行日期与状态；**不引入 Alembic**——当前 `create_all` + 幂等约束 + 一次性迁移脚本对单人/小团队维护成本最低，表结构变更频率不值得上迁移框架。

---

## 5. 可维护性与 AI Coding 友好性设计

数据和代码复杂化之后，维护的主要执行者会越来越多地是 AI Coding 工具。以下措施按"对 AI 工具的杠杆"排序：

### 5.1 把知识写进机器可读的位置

| 措施 | 现状/动作 |
|---|---|
| `CODEBUDDY.md` 持续更新 | 已有，本次架构落地后必须同步：新增"如何添加一个分析插件"的一节（即 4.1 的 Golden Path），这是 AI 工具做扩展时最需要的配方 |
| 每个插件目录自带 `README.md` 或 docstring 头部 | 说明输入表、输出结构、参数、边界条件；AI 工具改代码前读目录即可建立上下文 |
| `docs/` 保持"设计文档 + 评审报告"惯例 | 项目已有此惯例（v1.01 两份评审报告）。继续执行：每个阶段先出设计稿再动手，文档是 AI 工具理解"为什么这样写"的依据 |

### 5.2 保持文件小、职责单一

- 设定软约束：**单文件超过约 800 行即考虑拆分**。当前 `web/queries.py`（2322 行）是最大隐患，随插件化迁移自然拆分。
- 插件目录制天然限制文件膨胀——一个分析一个目录，AI 工具单次任务只需读一个目录而非全库。

### 5.3 类型与测试作为安全网

- 延续 SQLAlchemy 2.0 typed mapped columns、`dataclass` 行对象、`to_dict()` 的既有约定；`AnalysisSpec` / `AnalysisModule` 用抽象基类而非鸭子类型，让 IDE 和 AI 工具能静态发现接口违反。
- **DB-free 测试是第一优先级**：插件的 `compute.py` 不依赖数据库，测试构造内存数据（沿用 `test_similarity.py` 模式）。AI 工具改完代码能立刻 `pytest` 验证，这是自动化维护能成立的前提。需要 DB 的测试单独标记，不要求每次全量跑。

### 5.4 契约稳定，便于自动化回归

- CLI 的 JSON 输出 schema 视为契约：新增字段可以，改/删字段视为破坏性变更，需在文档注明。AI 工具升级某插件后，可用"同一参数跑同一命令 diff 输出"做快速回归。
- 退出码约定（0/1/2）继续严格执行。

### 5.5 明确"不做什么"

- 不拆微服务：单体 + 共享 PostgreSQL 在当前规模是最优解。
- 不引入插件框架库（如 pluggy）：注册表模式 30 行代码即可，与 collectors 同风格，零新依赖。
- 不提前做抽象：只有 `similarity` 之外的**第二个**分析真实落地时，插件框架的接口才最终定稿——先用 `holding_change` 或 `cluster_evolution` 验证抽象，避免凭空设计。
- 不给 LLM 子系统加记忆、RAG、向量库：第一版工具调用 + 数据概览摘要已覆盖核心价值，后续按真实使用反馈再扩展。

---

## 6. 落地路线图

按"先建轨道、再跑火车"排序，每期结束系统都处于可用状态：

### Phase 1：插件框架 + 首个分析（对应两份文档的 P0）

1. 实现 `analysis/base.py` + `registry.py` + `scripts/fundseeker_analysis.py`（list/run 两个命令）；
2. 以 `holding_change`（重仓股异动）为首个插件验证抽象——它数据来源最简单（两期 `product_holding` 对齐差分），业务价值最直接；
3. Web 增加 `/analysis` 目录页与通用 API；
4. 更新 `CODEBUDDY.md`（Golden Path 一节）。

### Phase 2：聚类演化展示（聚类展示建议文档的 P0/P1）

1. 实现 `cluster_evolution` 插件：时间区段对齐（resolve_report_dates）→ 单期回退 / 双期对比 / 多期时间轴三模式；
2. 该插件自带定制 Web 页面（Sankey 流向图等，见展示建议文档第 4、6 节）；
3. 验证"插件自带 web_routes + 模板"的扩展方式。

### Phase 3：LLM 对话分析

1. 实现 `assistant/` 四模块 + `fundseeker_assistant.py`；
2. 工具清单 = 已有插件注册表 + 产品搜索/持仓查询两个只读工具；
3. 灰度验证：先在 `--once` 单轮模式下跑通 10 个典型问题（"某基金最近换了哪些重仓股""哪类产品风格最稳定"），再开放交互模式。

### Phase 4：存量归拢与更多分析

1. 按优先级落地 `holding_evolution`、`industry_drift`、`trade_timing` 等插件（数据随季度积累逐步就绪，框架自动暴露新能力）；
2. 视情况将 `similarity/service.py` 中编排性代码逐步归拢，纯算法留在内核——**渐进式，不追求一次到位**；
3. `web/queries.py` 随插件迁移持续瘦身。

---

## 7. 风险与注意事项

- **抽象验证风险**：插件接口若一次定稿容易过度设计。对策见 5.5——首个插件落地前接口允许调整，落地后冻结。
- **双轨期复杂度**：Phase 1-2 期间 `similarity/cli_core.py` 与新 CLI 并存。对策：`fundseeker_similarity.py` 保持不变（它服务的是聚类内核，本就有清晰边界），不在过渡期强行合并入口。
- **LLM 成本与幻觉**：工具返回的 dict 可能很大，需在 `dispatch_tool` 层做结果截断/摘要；回答中强制携带数据来源字段，降低无依据陈述。
- **数据就绪度**：`min_report_periods` 自检要在 CLI/Web/LLM 三处一致地给出"数据不足"的明确提示，而不是让分析报错或返回空——数据积累期这是常态而非异常。

---

## 8. 总结

本方案的核心是一个判断和两个机制：

- **判断**：当前三层架构不需要推翻，缺的是"分析能力"维度的统一扩展点；采集层已有的注册表模式就是现成的答案模板。
- **机制一：分析插件注册表**（`analysis/`），让 CLI、Web、LLM 三个消费方共享同一能力目录——分析方法"方便扩展"与"统一管理"由同一机制保证。
- **机制二：LLM 工具桥**（`assistant/`），把插件注册表直接映射为 function-calling 工具目录，对话式分析作为纯消费方接入，零数据通道旁路。

可维护性上，靠"小文件 + 插件目录隔离 + DB-free 测试 + 稳定的 JSON 契约 + 持续更新的 `CODEBUDDY.md`"五件事，保证 AI Coding 工具始终能快速建立上下文、安全地改代码、立刻验证结果。落地按四个 Phase 推进，每期独立可用，风险可控。
