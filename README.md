# AstroAgent

面向天文科研的 AI Agent 平台。自然语言问题 → DeepSeek 工具调用 → SIMBAD 天体查询 / ADS 文献检索 / Gaia DR3 查询与基础统计 → 带来源的回答，使用 FastAPI 提供接口。

当前版本：`v0.3.0`，详见 [GitHub Release](https://github.com/lct808846/astroagent/releases/tag/v0.3.0)、[版本说明](docs/releases/v0.3.0.md) 和 [实际测试记录](docs/test-records/v0.3.0/README.md)。SIMBAD 相关联网成功路径尚未通过当日本机验收，本版按明确授权带此已知限制发布，不代表完整联网测试全部通过。

开发依据为 [V0.3 开发文档](docs/PROJECT_PLAN_V0.3.md)，原有能力见 [V0.2 开发文档](docs/PROJECT_PLAN_V0.2.md) 和 [V0.1 计划](docs/PROJECT_PLAN_V0.1.md)。本版本为单次、无状态查询；不包含前端、多用户、MCP、RAG 或复杂科研工作流。

Gaia 固定访问 `gaiadr3.gaia_source`：支持十进制字符串 DR3 `source_id` 精确查询，或 ICRS 中心与半径（最大 30 角分）的圆锥查询（最多 100 行，默认 20 行）。返回测量、误差、单位、参考历元、实际 ADQL 与截断状态；可按要求筛选 RUWE 和正视差信噪比。基础统计由程序计算，只描述实际交付行；总命中数未知，不自动翻页。

ADS 支持主题、标题、作者、年份范围、bibcode 与相关性/日期/被引次数排序。每次查询一页（1–10 篇，前 100 条范围），返回标题、完整作者列表、年份、出版物、全部 DOI、摘要、被引次数及程序构建的 ADS 链接。缺失数据保留空值；仅依据本次摘要总结，不下载或声称阅读全文。

SIMBAD 支持按名称查询主标识符、ICRS 赤经赤纬（度）、天体类型、光谱类型及坐标文献编号。缺失值保留为 `null`。名称 → Gaia 先单独查询 SIMBAD 坐标，失败则停止该链路。圆锥结果仅为位置候选源，不能直接认定名称匹配或星团成员；本版不做自行传播、成员判定或参数反演。

仅用户请求时，程序对正视差、正误差且 SNR≥10 的源计算 `1000/parallax` pc 和一阶随机误差；其他源保留跳过原因。近似距离未校正视差零点、系统误差或选择偏差，不是 Gaia 直接测得的距离，也不是贝叶斯距离估计。质量和年龄等未接入字段不补写。

## 环境与安装

使用 Python 3.12 或更高版本，以下命令在项目根目录的 PowerShell 中执行。

已有 conda `agent` 环境时：

```powershell
conda activate agent
python -m pip install -e ".[dev]"
```

在新机器上，可以先创建环境：

```powershell
conda create -n agent python=3.12
conda activate agent
python -m pip install -e ".[dev]"
```

`-e` 以可编辑方式安装项目，修改 `src/` 后无需重新安装；`dev` 包含 pytest 和用于接口测试的 HTTPX。

## 配置

聊天接口需要 DeepSeek API 密钥。文献检索另需 `ADS_API_TOKEN`，仅 SIMBAD / Gaia 查询可留空。启动、健康检查、接口文档和离线测试不需要密钥。ADS token 从 [官方 Access 说明](https://github.com/adsabs/adsabs-dev-api#access) 获取。

可在当前 PowerShell 会话中设置：

```powershell
$env:DEEPSEEK_API_KEY = "your-deepseek-api-key"
```

也可将 `.env.example` 复制为项目根目录的 `.env` 后填写。应用会自动加载它，进程环境变量优先；配置更改在下一次聊天请求生效。真实密钥不要写入代码或提交到 Git，`.env` 已被忽略。

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 空 | 聊天必需，缺失时返回 503 |
| `DEEPSEEK_MODEL` | `deepseek-flash` | 支持 Tool Calling 的模型 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | 模型服务地址 |
| `LLM_TIMEOUT_SECONDS` | `60` | 单次模型 HTTP 请求超时，关闭自动重试 |
| `SIMBAD_TIMEOUT_SECONDS` | `20` | SIMBAD 每次网络操作的连接、读取超时 |
| `ADS_API_TOKEN` | 空 | 执行 ADS 时必需，缺失产生逐条 `ads_not_configured` 错误 |
| `ADS_TIMEOUT_SECONDS` | `20` | ADS 连接/读取各自超时，须大于 0 且不超过 120 秒 |
| `GAIA_TIMEOUT_SECONDS` | `20` | Gaia 连接/读取各自超时，须大于 0 且不超过 120 秒，无 Archive token |
| `AGENT_MAX_ROUNDS` | `4` | 一次聊天最多模型调用轮数 |
| `AGENT_MAX_TOOL_CALLS` | `6` | SIMBAD、ADS 与 Gaia 共享的工具调用上限 |

模型按 [DeepSeek 官方工具调用示例](https://api-docs.deepseek.com/guides/tool_calls/) 使用非思考模式。网络超时不是整个聊天的总耗时上限。ADS 固定请求官方 API、使用 Bearer 头，关闭重定向和自动重试。Windows 用户环境变量更改后，需新开终端并重启已有服务才能继承。

## 运行

```powershell
conda activate agent
python -m uvicorn astroagent.main:app --reload
```

- 健康检查：<http://127.0.0.1:8000/health>
- 聊天查询：`POST http://127.0.0.1:8000/api/v1/chat`
- 交互接口文档：<http://127.0.0.1:8000/docs>
- OpenAPI 定义：<http://127.0.0.1:8000/openapi.json>

`GET /health` 返回 HTTP 200 和以下 JSON：

```json
{"status": "ok"}
```

它仅检查服务能够响应请求，不检查外部模型或数据库的可用性。默认绑定本机，适合个人开发使用。

## 发起查询

在 `/docs` 中展开 `POST /api/v1/chat`，输入：

```json
{"message": "请查询 Betelgeuse 的坐标、天体类型和光谱类型，并给出来源。"}
```

文献或综合查询示例：

```json
{"message": "检索 2020—2026 年 Betelgeuse 变暗相关论文，取 3 篇，按发表时间降序，给出来源。"}
```

```json
{"message": "查询 Betelgeuse 的坐标，再找 2 篇有关其变暗的论文，给出来源。"}
```

Gaia 查询示例（每次请求包含完整条件）：

```json
{"message": "查询 Gaia DR3 source_id 5853498713190525696 的测量信息并估算距离，说明近似条件与未做的校正。"}
```

```json
{"message": "以 ICRS 赤经 56.75 度、赤纬 24.12 度为中心，查 5 角分内最近的 20 个 Gaia DR3 位置候选源，总结视场自行，不估算距离。"}
```

```json
{"message": "先查 M45 的 SIMBAD 坐标，再查其中心附近 5 角分内最近的 3 个 Gaia DR3 源；筛选 RUWE≤1.4、正视差信噪比≥10，并说明成员和历元限制。"}
```

或使用 PowerShell：

```powershell
$body = @{ message = "请查询 Betelgeuse 的坐标和类型，并给出来源。" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/chat `
  -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) |
  ConvertTo-Json -Depth 10
```

响应包含：

| 字段 | 含义 |
| --- | --- |
| `status` | `success` 全部完成；`partial` 部分成功或回答生成未完成；`error` 所有已执行的数据库查询均失败或无匹配 |
| `answer` | 模型生成的自然语言解释，或回答生成失败时的明确提示 |
| `results` | 逐次工具查询的实际结果，包括输入名称、状态、数据、来源和错误 |
| `literature_results` | 逐次 ADS 调用，含实际检索式、固定筛选、分页、总命中数、完整文献和失败原因 |
| `gaia_results` | 逐次 Gaia 调用，含有效参数、发布版、ADQL、测量与单位、统计/距离、截断及错误 |
| `sources` | 成功 SIMBAD 查询、ADS 各篇论文及 Gaia Archive 来源、UTC 时间，按 URL 去重且保留首次成功记录 |
| `warnings` | 已取得查询结果后发生的模型失败或调用限制 |

`results[].data`、`literature_results[].papers` 与 `gaia_results[].data/analysis` 用于核查实际数据；`answer` 由模型生成，仍需科研核查。概念问题可以不调用工具，此时三个结果列表和 `sources` 为空。失败/无匹配的尝试链接仍在各条 `source` 中，ADS 搜索页也只保留在该次检索中，不进入成功来源列表。

`total_found` 是数据库命中数，`returned_count` 是本页去重后数量，`has_more` 按原始页大小计算；本页无数据不一定意味着整个检索无匹配。API 保留完整摘要与作者，模型视图只提供摘要前 2000 字符及前 5 位作者并标记截断。相对年份按请求时 UTC 日期解释，用户指定时区时按指定时区解释。

Gaia 用多取一行判断截断，哨兵行不进入交付数据或统计；`total_found` 恒为 `null`。`archive_overflow` 单独记录服务端溢出。模型只看前 10 行及其距离，但接收完整样本统计与计算/跳过数量；API 保留最多 100 行。负/零视差不默认删除，缺失测量为 `null`，`source_id` 始终是字符串，避免大整数精度损失。`pmra` 已含赤纬余弦因子。

兼容性：路径和请求格式保留；相对 V0.2 响应新增 `gaia_results=[]`，`Source.name` 增加 `Gaia`。拒绝未知响应字段或固定来源枚举的客户端需要更新。旧 `results` 仍只含 SIMBAD，`literature_results` 仍只含 ADS。

输入 `message` 去除首尾空白后须为 1–4000 个字符，不接受额外字段。每次请求独立处理，不保留会话历史。

## 错误处理

| 情况 | 接口行为 |
| --- | --- |
| 无效或空白输入 | HTTP 422，FastAPI 验证信息 |
| 缺失密钥、配置错误、模型认证失败或限流 | HTTP 503，`error.code` 和中文说明 |
| 模型网络失败、无效工具调用、空回答 | HTTP 502 |
| 模型超时 | HTTP 504 |
| SIMBAD 未匹配、超时或不可用 | HTTP 200，查看 `status` 与 `results[].error`；无成功数据来源 |
| ADS 未配置、认证失败、限流、超时、无匹配或异常响应 | HTTP 200，查看 `literature_results[].status/error`；不以记忆生成论文 |
| Gaia 无匹配、超时、限流、拒绝、TAP 错误、坏 XML 或响应体超限 | HTTP 200，查看 `gaia_results[].status/error`；保留其他工具已成功的数据 |
| 已有结果后模型失败、超出轮数或调用次数 | HTTP 200，保留结果并返回 `warnings` |

外部异常信息经过清理，不向接口返回原始异常或密钥。SIMBAD 查询使用 [astroquery 官方名称查询接口](https://astroquery.readthedocs.io/en/latest/simbad/simbad.html)，ADS 使用 [官方 Search API](https://github.com/adsabs/adsabs-dev-api/blob/master/API_documentation_Python/Search_API_Python.ipynb)。每批工具先验证再执行，未知工具被拒绝。

## 测试

```powershell
conda activate agent
python -m pytest -q
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
```

默认测试禁止外部 HTTP，不需要 API 密钥。真实服务测试需显式启用，会产生模型 API 用量：

```powershell
$env:ASTROAGENT_RUN_LIVE = "1"
python -m pytest tests/test_live.py -v
Remove-Item Env:ASTROAGENT_RUN_LIVE
```

实际启动 Uvicorn、验收 HTTP 接口并自动停止服务：

```powershell
python scripts/verify_live.py
```

该脚本验证健康检查、文档、OpenAPI、空白输入、Betelgeuse 查询和无效天体名称。报告与服务日志按版本和 UTC 运行时间保存到 `docs/test-records/v<版本>/acceptance/<运行时间>/`，每次新建目录，不覆盖历史记录。

其他测试记录也可自动归档：

```powershell
python scripts/run_tests.py          # 离线测试、Ruff 和依赖检查，保存输出与 JUnit XML
python scripts/run_tests.py --live   # 真实服务测试，会产生模型用量
python scripts/run_tests.py --live-ads # 独立启用 ADS 与综合聊天测试
python scripts/run_tests.py --live-gaia # 独立 Gaia、真实模型、名称衔接和三工具测试
python scripts/verify_v03.py         # V0.3 十二项真实 HTTP 验收并停止临时服务
python scripts/verify_v02.py         # V0.2 九项真实 HTTP 验收并停止临时服务
python scripts/measure_latency.py    # 测量已启动服务的延迟，默认 3 次真实查询
```

Gaia 的 pytest 独立开关为 `ASTROAGENT_RUN_LIVE_GAIA=1`；ADS 使用 `ASTROAGENT_RUN_LIVE_ADS=1`。三个开关互不启用，默认归档入口全部关闭它们。显式启用后缺密钥或外部失败会报错，不能当作跳过。Gaia 直接查询测试无需密钥，模型及联合场景需已有相应配置。

记录入口见 [分版本测试记录](docs/test-records/README.md)，当前记录见 [v0.3.0](docs/test-records/v0.3.0/README.md)。完整范围见 [测试文档](docs/TESTING.md)。GitHub Actions 配置为每次 push / PR 执行离线测试与 Ruff 检查；远程运行状态须在推送后查看。

## 目录

```text
astroagent/
├── src/astroagent/
│   ├── __init__.py
│   ├── main.py              # 应用、路由与错误响应
│   ├── config.py            # 环境变量与 .env
│   ├── agent.py             # LangChain 工具调用循环
│   ├── simbad.py            # 真实 SIMBAD 查询与字段转换
│   ├── ads.py               # 真实 ADS 单页检索与字段验证
│   ├── gaia.py              # 固定 DR3 同步 TAP、严格 VOTable 与资源边界
│   ├── analysis.py          # 返回样本统计与条件式距离近似
│   ├── schemas.py           # 请求、结果、来源与错误模型
│   ├── errors.py            # 对外安全错误
│   └── api/
│       ├── __init__.py
│       ├── chat.py          # POST /api/v1/chat
│       └── health.py        # GET /health
├── tests/
│   ├── test_health.py
│   ├── test_chat.py
│   ├── test_config.py
│   ├── test_simbad.py
│   ├── test_ads.py
│   ├── test_literature_chat.py
│   ├── test_live_ads.py
│   ├── test_gaia.py
│   ├── test_analysis.py
│   ├── test_gaia_chat.py
│   ├── test_live_gaia.py
│   └── test_live.py
├── scripts/verify_live.py
├── .github/workflows/test.yml
├── docs/
│   ├── PROJECT_PLAN_V0.1.md
│   ├── PROJECT_PLAN_V0.2.md
│   ├── PROJECT_PLAN_V0.3.md
│   └── TESTING.md
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```
