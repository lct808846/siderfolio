# AstroAgent

面向天文科研的 AI Agent 平台。自然语言问题 → DeepSeek 工具调用 → SIMBAD 天体查询 / ADS 文献检索 / Gaia DR3 查询与基础统计 → 带来源的回答，使用 FastAPI 提供接口。

当前版本：`v0.5.0`，新增中文 Web 工作台、本地会话与连续对话、历史核查和同包图表预览/下载。见 [版本说明](docs/releases/v0.5.0.md)、[实际测试记录](docs/test-records/v0.5.0/README.md) 与 [源码发布页](https://github.com/lct808846/astroagent/releases/tag/v0.5.0)。SIMBAD 相关完整联网成功路径仍未通过，本版保留该已知限制。

本版按 2026-10-29 用户“发布新版本”的指令执行源码发布流程，保留当日 SIMBAD 超时复验和失败证据。历史版本见 [`v0.4.0`](https://github.com/lct808846/astroagent/releases/tag/v0.4.0)。

开发依据为 [V0.5 开发文档](docs/PROJECT_PLAN_V0.5.md)。网页通过独立会话接口保存历史；原 `POST /api/v1/chat` 保持单次、无状态语义。本版仅面向可信本机的单用户使用，不包含账号、多用户、公网/LAN 部署、MCP、RAG 或复杂科研工作流。

导出契约与完成门槛见 [V0.4 开发文档：查询结果可视化与可复现导出](docs/PROJECT_PLAN_V0.4.md)。`POST /api/v1/exports` 接收完整客户端快照，独立于模型和外部数据库，可无密钥使用。

前端采用 Vue 3 + TypeScript + Vite、Vue Router 和 Pinia，后端使用 FastAPI 与标准库 SQLite。后续 V0.6–V2.0 的目标、依赖与验收门槛统一见 [版本路线图](docs/ROADMAP.md)。

下一版本的项目管理、查询归档、重跑及比较方案见 [V0.6 开发文档](docs/PROJECT_PLAN_V0.6.md)；该版本目前处于规划阶段。

## 本机网页使用

需要 Python 3.12+ 和 Node.js 24.15+（本轮验证版本24.22.1，npm10.9.2）。先按下节安装后端并在服务端配置密钥。前端不接收或保存模型密钥、ADS token。

在第一个 PowerShell 终端启动后端，保持单进程、单 worker：

```powershell
conda activate agent
python -m uvicorn astroagent.main:app --host 127.0.0.1 --port 8000 --workers 1
```

在第二个终端，从项目根目录进入前端，安装锁定依赖并启动构建产物：

```powershell
cd frontend
npm ci
npm run build
npm run serve
```

Windows也可在项目根目录运行 `powershell -File scripts/frontend.ps1 -Mode build`，再运行 `powershell -File scripts/frontend.ps1 -Mode serve`。脚本优先使用已安装的Node24.15+（24.x）；若当前Node不受支持，可使用已存在的Codex内置Node，或显式传入 `-NodePath`。它不替换系统Node，也不修改全局配置。

打开 <http://127.0.0.1:5173>。新建会话，输入完整首问，再基于已保存结果追问；右侧按轮次核查三类结果、完整表格、条件与来源。选择图种后点击“生成预览与数据包”，预览和下载来自同一个 ZIP。改选轮次或图种后需要重新生成；不足绘图条件时保留具体跳过原因。

会话默认保存在 `.astroagent/astroagent.sqlite3`，刷新与服务重启后可以恢复。断线只代表网页停止等待，不保证后端已取消；先点击“恢复会话 / 刷新状态”核对，不要重复执行。已有运行中轮次在服务重启后标为“中断”，不会自动重放收费请求。删除会话前需要确认，不影响已下载到其他目录的文件。

预览包仅缓存于内存，15分钟后或重启后失效；回到原轮次显式重新生成。缺少模型密钥时仍可读取历史及生成历史结果的预览/导出。SQLite不可写时会话接口明确报错；健康、接口文档及旧无状态入口仍可启动。

前端开发时用 `npm run dev` 代替构建/静态服务，同样只监听127.0.0.1:5173且端口占用即失败。默认两种前端服务都把 `/api`、`/health` 代理至127.0.0.1:8000；构建静态服务不把API错误回退成HTML。直接跨源联调可在前端独立环境文件设置公开的 `VITE_API_BASE_URL`，后端配置明确的 `ASTROAGENT_ALLOWED_ORIGINS` JSON数组；不使用通配来源，前端环境变量中不得包含凭证。

本地限制：最多20个会话、每会话40个已接受轮次；全局最多两轮模型任务，不排队；请求32 KiB，单轮16 MiB，全库业务内容及预留256 MiB。历史模型窗口最近六轮且至多64 KiB，整轮裁剪并提示遗漏；不改写原始完整结果。该字节预算不是供应商token容量保证，模型调用前另保留当前输入、工具与输出预算。

数据库目录通过 `ASTROAGENT_DATA_DIR` 配置，必须在后端本机磁盘。数据库schema迁移前使用SQLite备份接口，未知更高版本拒绝降级写入。数据库和前端构建缓存不进入源码归档。本版不支持多worker或多个进程共享会话库；不要通过绑定0.0.0.0将无登录工具暴露到公网或LAN。

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
- 结果导出：`POST http://127.0.0.1:8000/api/v1/exports`
- 本地会话：`/api/v1/conversations`、`/{id}/turns`
- 轮次产物：`/api/v1/conversations/{id}/turns/{turn_id}/artifacts`
- 清单/图片/下载：`/api/v1/artifacts/{artifact_id}/...`
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

## 导出数据与图表

先取得聊天接口的完整响应，再显式提交导出请求。两次请求独立，服务不保存历史；仅在自然语言中要求“画图”不会自动执行导出。

```python
from pathlib import Path
import requests

base = "http://127.0.0.1:8000"
chat = requests.post(base + "/api/v1/chat", json={
    "message": "查询 ICRS 赤经56.75度、赤纬24.12度、半径5角分内最近100个Gaia DR3位置候选源。"
}, timeout=240)
chat.raise_for_status()
snapshot = chat.json()  # 完整响应，不能使用模型前10行视图
export = requests.post(base + "/api/v1/exports", json={
    "schema_version": "1",
    "snapshot": snapshot,
    "plots": [
        {"gaia_result_index": 0, "kind": "proper_motion"},
        {"gaia_result_index": 0, "kind": "parallax_histogram"},
        {"gaia_result_index": 0, "kind": "observed_cmd"},
    ] if snapshot["gaia_results"] else [],
}, timeout=60)
export.raise_for_status()
Path("astroagent-results.zip").write_bytes(export.content)
```

也可以把已保存的 V0.3 / V0.4 完整响应作为 `snapshot`，设置 `plots=[]` 仅导出数据。最多选择三张图，索引对应 `gaia_results`，同一索引和图种不能重复。

ZIP 包含完整 `snapshot.json`、每次成功查询的固定列 CSV、所选 PNG、中文 `README.md` 和 `manifest.json`。清单记录查询/来源/单位/截断、运行版本、逐行绘图选择、跳图原因、CSV 文本处理位置及每个文件的 SHA-256。失败与无匹配保留原状态，不生成伪数据表；不足两行有效视差时跳过直方图，其他文件仍可下载。

图表只描述本次交付样本：自行等比例、视差保留负值与零值、观测颜色—星等图的亮源在上。图表不作成员判定、消光/零点校正、年龄拟合或新的距离推断。CSV 用 UTF-8 BOM，危险文本和长 `source_id` 加前导单引号；精确原文、编号和空值以 JSON 为准。

快照由客户端提交，包内固定标注来源真实性未经认证；哈希用于核对文件变化，不是来源签名。接口限制实际请求体 2 MiB、总查询 12 次、单次 Gaia 100 行、ADS 10 篇、包内总字节与 ZIP 各 16 MiB。每进程同时一次导出；不支持压缩请求体，不提供公共文件目录或长期链接。

成功响应为 `application/zip`，固定文件名 `astroagent-results.zip`、`Cache-Control: no-store`。查询状态与清单的 `export_status` 独立；存在跳图时后者为 `partial`。

| 导出异常 | HTTP / 错误码 |
| --- | --- |
| 非法 JSON、未知字段、坏索引或不一致快照 | 422 / `invalid_export_snapshot` |
| 请求体或包体超限 | 413 / `export_too_large` |
| 非 JSON 或非 identity 编码 | 415 / `unsupported_export_media_type` |
| 进程内导出正忙 | 503 / `export_busy` |
| 核心打包失败 | 500 / `export_failed` |

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
python scripts/verify_v04.py         # 合成数据的真实 HTTP 导出验收，无密钥
python scripts/verify_v04.py --live  # 真实查询→导出，会产生模型用量
python scripts/verify_v05.py         # 合成替身的真实HTTP、追问、幂等与重启恢复
python scripts/verify_v05.py --live  # 真实会话/条件继承/历史引用，会产生模型用量
python scripts/run_frontend_checks.py # npm ci、类型、ESLint、Vitest、构建和契约
python scripts/run_frontend_checks.py --browser # 生产dist的Chromium/Edge验收
python scripts/verify_package.py     # 独立wheel安装与无密钥API验收，不发布安装器
python scripts/verify_v02.py         # V0.2 九项真实 HTTP 验收并停止临时服务
python scripts/measure_latency.py    # 测量已启动服务的延迟，默认 3 次真实查询
```

Gaia 的 pytest 独立开关为 `ASTROAGENT_RUN_LIVE_GAIA=1`；ADS 使用 `ASTROAGENT_RUN_LIVE_ADS=1`。三个开关互不启用，默认归档入口全部关闭它们。显式启用后缺密钥或外部失败会报错，不能当作跳过。Gaia 直接查询测试无需密钥，模型及联合场景需已有相应配置。

浏览器检查前在 `frontend/` 执行 `npx playwright install chromium`；Windows同时使用已安装的Edge，Linux仅运行Chromium。检查脚本可用 `NODE_BINARY` 指定已安装的受支持Node可执行文件；浏览器测试采用专用合成库，不访问个人会话库。

记录入口见 [分版本测试记录](docs/test-records/README.md)，当前记录见 [v0.5.0](docs/test-records/v0.5.0/README.md)。完整范围见 [测试文档](docs/TESTING.md)。GitHub Actions 包含后端检查、独立前端构建与浏览器任务；发布须等待目标提交及标签的 CI 全部通过，执行情况见 [Actions](https://github.com/lct808846/astroagent/actions)。

## 目录

```text
astroagent/
├── frontend/               # 独立Vue/TypeScript工程、生产静态服务、组件与浏览器测试
├── src/astroagent/
│   ├── __init__.py
│   ├── main.py              # 应用、路由与错误响应
│   ├── config.py            # 环境变量与 .env
│   ├── agent.py             # LangChain 工具调用循环
│   ├── simbad.py            # 真实 SIMBAD 查询与字段转换
│   ├── ads.py               # 真实 ADS 单页检索与字段验证
│   ├── gaia.py              # 固定 DR3 同步 TAP、严格 VOTable 与资源边界
│   ├── analysis.py          # 返回样本统计与条件式距离近似
│   ├── export_schemas.py    # 严格快照与导出契约
│   ├── exports.py           # 固定列 CSV、JSON、ZIP 与校验清单
│   ├── plots.py             # 全交付样本选行、分箱与无 GUI PNG
│   ├── conversations.py    # SQLite迁移、短事务、幂等、配额与恢复
│   ├── conversation_service.py # 同会话一轮、全局两轮模型任务
│   ├── context.py           # 整轮有界历史窗口及引用记录
│   ├── artifacts.py         # 缓存ZIP、清单与白名单图片
│   ├── local_access.py      # 本机Host/Origin与会话接收限制
│   ├── schemas.py           # 请求、结果、来源与错误模型
│   ├── errors.py            # 对外安全错误
│   └── api/
│       ├── __init__.py
│       ├── chat.py          # POST /api/v1/chat
│       ├── exports.py       # POST /api/v1/exports、接收字节上限
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
│   ├── test_exports.py
│   └── test_live.py
├── scripts/verify_live.py
├── .github/workflows/test.yml
├── docs/
│   ├── PROJECT_PLAN_V0.1.md
│   ├── PROJECT_PLAN_V0.2.md
│   ├── PROJECT_PLAN_V0.3.md
│   ├── PROJECT_PLAN_V0.4.md
│   ├── PROJECT_PLAN_V0.5.md
│   ├── ROADMAP.md
│   └── TESTING.md
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```
