# AstroAgent

面向天文科研的 AI Agent 平台。V0.1 已实现自然语言问题 → DeepSeek 工具调用 → SIMBAD 真实查询 → 带来源的回答，使用 FastAPI 提供接口。

当前发布版本：`v0.1.0`，详见 [发布说明](docs/releases/v0.1.0.md)。

开发依据为 [项目计划 V0.1](docs/PROJECT_PLAN_V0.1.md)。本版本为单次、无状态查询；不包含前端、多用户、MCP、RAG 或复杂科研工作流。

下一版本的范围与实现方案见 [V0.2 开发文档：ADS 文献检索](docs/PROJECT_PLAN_V0.2.md)；该文档为待实现设计，当前运行版本仍为 V0.1。

支持按天体名称查询主标识符、ICRS 赤经赤纬（度）、天体类型、光谱类型及坐标文献编号。缺失值保留为 `null`。查询结果由程序直接记录，来源不依赖模型生成；距离、质量、亮度等字段尚未接入。

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

聊天接口需要 DeepSeek API 密钥。启动、健康检查、接口文档和离线测试不需要密钥。

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
| `AGENT_MAX_ROUNDS` | `4` | 一次聊天最多模型调用轮数 |
| `AGENT_MAX_TOOL_CALLS` | `6` | 一次聊天最多工具调用次数 |

模型按 [DeepSeek 官方工具调用示例](https://api-docs.deepseek.com/guides/tool_calls/) 使用非思考模式。SIMBAD 超时按网络操作计算，一次查询可能有多次元数据请求，并非整个聊天的总耗时上限。

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
| `sources` | 成功查询的 SIMBAD 链接和 UTC 查询时间，按链接去重 |
| `warnings` | 已取得查询结果后发生的模型失败或调用限制 |

`results[].data` 是数据库字段的直接映射，应以它核对数值。`answer` 由模型生成，仍需科研核查。概念问题可以不调用工具，此时 `results`、`sources` 为空。未匹配或失败查询的链接保留在各自的 `results[].source`，其中时间表示查询尝试时间，不代表成功获得数据。

输入 `message` 去除首尾空白后须为 1–4000 个字符，不接受额外字段。每次请求独立处理，不保留会话历史。

## 错误处理

| 情况 | 接口行为 |
| --- | --- |
| 无效或空白输入 | HTTP 422，FastAPI 验证信息 |
| 缺失密钥、配置错误、模型认证失败或限流 | HTTP 503，`error.code` 和中文说明 |
| 模型网络失败、无效工具调用、空回答 | HTTP 502 |
| 模型超时 | HTTP 504 |
| SIMBAD 未匹配、超时或不可用 | HTTP 200，查看 `status` 与 `results[].error`；无成功数据来源 |
| 已有结果后模型失败、超出轮数或调用次数 | HTTP 200，保留结果并返回 `warnings` |

外部异常信息经过清理，不向接口返回 SDK 原始异常或密钥。SIMBAD 查询使用 [astroquery 官方名称查询接口](https://astroquery.readthedocs.io/en/latest/simbad/simbad.html)，不执行模型传入的 SQL、命令或未知工具。

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
python scripts/measure_latency.py    # 测量已启动服务的延迟，默认 3 次真实查询
```

记录入口见 [分版本测试记录](docs/test-records/README.md)，当前记录见 [v0.1.0](docs/test-records/v0.1.0/README.md)。完整范围见 [测试文档](docs/TESTING.md)。GitHub Actions 配置为每次 push / PR 执行离线测试与 Ruff 检查；远程运行状态须在推送后查看。

## 目录

```text
astroagent/
├── src/astroagent/
│   ├── __init__.py
│   ├── main.py              # 应用、路由与错误响应
│   ├── config.py            # 环境变量与 .env
│   ├── agent.py             # LangChain 工具调用循环
│   ├── simbad.py            # 真实 SIMBAD 查询与字段转换
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
│   └── test_live.py
├── scripts/verify_live.py
├── .github/workflows/test.yml
├── docs/
│   ├── PROJECT_PLAN_V0.1.md
│   ├── PROJECT_PLAN_V0.2.md
│   └── TESTING.md
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```
