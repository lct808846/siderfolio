# V1.8 Astronomy MCP Server 部署、使用与排查说明

V1.8.0 将 AstroAgent 现有的 **SIMBAD 天体查询**、**ADS 文献检索** 与 **Gaia DR3 查询** 封装为可独立运行的本地 **Astronomy MCP Server**（`stdio`），并在 AstroAgent 后端接入固定 MCP Client 适配器。项目、会话、RAG 文档、绘图、V1.7 N 体计算任务及文件操作不在 MCP 工具清单内。

## 1. 锁定版本与协议契约（M0）

| 组件 | 锁定版本 / 目标 | 说明 |
| --- | --- | --- |
| AstroAgent | `1.8.0` | 同时提供独立 MCP Server 与宿主 MCP Client |
| Python 运行时 | `>=3.12`（容器为 `3.12.13`） | 无需 PostgreSQL、模型密钥或 FastAPI 即可启动独立 MCP Server |
| 官方 Python MCP SDK | `mcp==2.3.0`（`mcp-types==2.3.0`） | 可选依赖 `astroagent[mcp]`；后端容器依赖锁已固定 |
| 目标协议与传输 | `2026-07-28` / `stdio` | AstroAgent 客户端通过 `server/discover` 核验 `2026-07-28` 与 `tools` 能力，再执行 `tools/list` 和 `tools/call`；首期无 MCP HTTP 端口 |
| 外部验收客户端 | `@modelcontextprotocol/inspector@2.16.0` | 验收运行时为 Node.js 24.22.1 或更高的 24.x。指定现代协议模式并记录实际协商版本 |

### 固定工具清单与输出信封

服务端仅暴露三项只读工具，均声明 `readOnlyHint=true`、`destructiveHint=false` 及输入/输出 JSON Schema：

- `query_simbad`：按 1–200 字符天体名称/标识符查询 SIMBAD（无通配符，沿用 CDS 主站 → Harvard 镜像策略）。
- `search_ads`：检索 `database:astronomy` 单页文献（`query` URL 编码后 ≤ 1000 字符，`rows` 1–10，`start` 0–90，`start + rows <= 100`）。
- `query_gaia`：只读查询 `gaiadr3.gaia_source`（`mode=source_id` 使用正 64 位有符号整数字符串且与圆锥参数互斥；`mode=cone` 要求 ICRS 度制坐标、`radius_arcmin` ∈ `(0, 30]`、`limit` 1–500）。

所有 `tools/call` 响应同时返回 `structuredContent` 与同内容的 `text` 兼容块：

```json
{
  "schema_version": 1,
  "tool": "query_simbad",
  "result": { "...": "原 schemas.py 结果模型；正常、not_found 或业务错误均保留" },
  "error": null
}
```

- `success` / `not_found` / 截断结果：`isError` 为 `false`，外层 `error` 为 `null`。
- 查询服务业务/上游失败（如 `ads_not_configured`、`simbad_timeout`、`gaia_rate_limited`）：`isError` 为 `true`，`result` 保留完整结构化失败对象（`result.status == "error"`、`result.error` 与查询目标链接），外层 `error` 为 `null`。
- 适配器层失败（参数无效、超限、服务端并发饱和或超时）：`isError` 为 `true`，`result` 为 `null`，外层 `error` 含脱敏 `{code, message, retryable}`。
- 未知工具名或不合法 JSON-RPC 结构：直接返回 JSON-RPC 错误（`-32602` / `-32600` / `-32700`），不发起上游请求。

### 资源与并发限值

| 配置变量 | 默认值 | 合法范围 | 作用 |
| --- | --- | --- | --- |
| `ASTROAGENT_ASTRONOMY_TOOL_TRANSPORT` | `direct` | `direct` \| `mcp` | AstroAgent 聊天工具传输开关；升级默认沿用 `direct` |
| `ASTROAGENT_MCP_STARTUP_TIMEOUT_SECONDS` | `15` | `1–60` | 客户端启动子进程、`server/discover` 与 `tools/list` 总时限（秒） |
| `ASTROAGENT_MCP_CALL_TIMEOUT_SECONDS` | `60` | `1–180` | 单次 MCP 工具调用总时限（秒） |
| `ASTROAGENT_MCP_MAX_MESSAGE_BYTES` | `8388608`（8 MiB） | `64 KiB–16 MiB` | 单条 JSON-RPC 响应帧字节上限；超限明确报错，不截断 |
| `ASTROAGENT_MCP_MAX_REQUEST_BYTES` | `262144`（256 KiB） | `4 KiB–1 MiB` | 单条 JSON-RPC 请求帧字节上限 |
| `ASTROAGENT_MCP_POOL_SIZE` | `2` | `1–4` | AstroAgent 客户端子进程连接池上限，每连接同时执行 1 个调用 |
| `ASTROAGENT_MCP_ACQUIRE_TIMEOUT_SECONDS` | `5` | `0.1–60` | 等待空闲连接槽的最长时间（秒） |
| `ASTROAGENT_MCP_SERVER_MAX_CONCURRENCY` | `2` | `1–4` | 独立运行 MCP Server 时的单进程并发查询上限 |
| `ASTROAGENT_MCP_SERVER_MAX_QUEUE_WAIT_SECONDS` | `5` | `0.1–60` | 独立运行 MCP Server 时的排队等待上限（秒） |

## 2. Windows 本机启动

### 2.1 安装可选 MCP 依赖

在现有 Python 3.12 环境（例如 `D:\astroagent-runtime\venv` 或 conda `agent`）安装 `mcp` 依赖：

```powershell
python -m pip install -e ".[mcp]"
```

### 2.2 独立启动 Astronomy MCP Server

独立 MCP Server **仅从进程环境变量读取查询配置**（不读取 `.env`、不需要 PostgreSQL 或模型 API 密钥）。ADS token 须在受信本机环境中显式注入进程环境，切勿写入启动参数、共享样例或前端配置：

```powershell
# 仅查询 SIMBAD 和 Gaia 时可不设置 ADS_API_TOKEN（此时 ADS 返回 ads_not_configured）
$env:ADS_API_TOKEN = "<your-ads-token>"
python -m astroagent.mcp_server
```

启动后，标准输出仅承载 MCP JSON-RPC 帧；脱敏结构化日志（含 `correlation_id`、`tool`、`protocol_version`、`duration_ms`、`result_status`、`returned_count`、`error_code`）输出到标准错误，不包含查询全文、摘要、用户标识、凭据或原始上游异常。

### 2.3 在 Windows 本机 AstroAgent 中启用 MCP

在启动 FastAPI 后端的同一 PowerShell 终端中设置（其余模型与数据库配置沿用现有设置）：

```powershell
$env:ASTROAGENT_ASTRONOMY_TOOL_TRANSPORT = "mcp"
python -m uvicorn astroagent.main:app --host 127.0.0.1 --port 8000 --workers 1
```

切回直连模式时将环境变量改回 `direct`（或删除该变量）并重启后端。

## 3. Linux 容器部署与切换

V1.8 容器部署沿用现有身份（V1.6）与计算（V1.7）部署的 Compose 项目、私有环境文件、秘密文件和数据卷，**不开放新端口，不改动 PostgreSQL 架构或数据卷**。新增的 `compose.mcp.yaml` 将 `backend`、`frontend` 和入口代理 `ingress` 更新至 `1.8.0` 标签，并透传 `ASTRONOMY_TOOL_TRANSPORT`（默认 `direct`）。

### 3.1 更新容器镜像

使用项目维护脚本（自动组合 `compose.yaml`、`compose.plotting.yaml`、`compose.identity.yaml`、私有共享模型覆盖、`compose.compute.yaml` 与 `compose.mcp.yaml`）：

```powershell
powershell -File scripts/containers.ps1 -Action up
```

或使用显式 Compose 命令更新 `backend`、`frontend` 和 `ingress`（保留现有 `compute-worker`、`postgres`、`ollama`、`plot-executor` 及所有数据卷）：

```powershell
docker compose --env-file .astroagent/container/deployment-v16.env `
  -f compose.yaml -f compose.plotting.yaml -f compose.identity.yaml `
  -f .astroagent/container/compose-v16-shared-model.yaml `
  -f compose.compute.yaml -f compose.mcp.yaml `
  up -d --no-deps --build backend frontend ingress
```

### 3.2 启用 MCP 与切回直连

支持 **网页开关（推荐，免重启容器）** 或 **环境变量** 两种方式：

#### 方式 A：在网页「本机设置」一键切换（仅 MFA 已验证管理员）

1. 管理员登录网页，进入 **「本机设置 → 概览 → Astronomy MCP 通道」**。
2. 打开 **「通过本地 MCP 执行天文查询」** 开关：
   - 服务端会立即在容器内启动固定模块 `python -m astroagent.mcp_server` 并核验 `2026-07-28` 协议及三项工具清单；核验通过后持久化到既有控制面表 `public.auth_meta`（`astronomy_tool_transport_v1`），后续聊天查询立即生效且容器重启后保留。
   - 若当前有对话正在执行，会提示等待该轮完成后再切换；若核验失败，不会误保存开关状态。
3. 关闭该开关即可立即切回 `direct` 直连模式并回收空闲 MCP 子进程。

#### 方式 B：通过私有环境文件配置初始默认通道

1. **启用 MCP**：在私有环境文件（例如 `.astroagent/container/deployment-v16.env`）中设置：
   ```env
   ASTRONOMY_TOOL_TRANSPORT=mcp
   ```
   然后更新后端容器：
   ```powershell
   docker compose --env-file .astroagent/container/deployment-v16.env `
     -f compose.yaml -f compose.plotting.yaml -f compose.identity.yaml `
     -f .astroagent/container/compose-v16-shared-model.yaml `
     -f compose.compute.yaml -f compose.mcp.yaml `
     up -d backend
   ```
   后端容器启动后会在容器内部以固定命令 `python -m astroagent.mcp_server` 启动子进程，仅把 `ADS_API_TOKEN`（来自 `/run/secrets/backend_settings`）与查询超时注入子进程环境，排除模型、数据库、认证与代理凭据。
2. **确认当前正在使用 MCP**：
   - 管理员登录网页，打开「本机设置 → 概览 → Astronomy MCP 通道」，确认状态胶囊显示 **MCP 已就绪** 及 `协议 2026-07-28 · query_simbad / search_ads / query_gaia`。
   - 或已登录管理员请求 `GET /api/v1/setup/status`，核对 `astronomy_tool_transport == "mcp"`、`mcp_status == "ready"`、`mcp_protocol_version == "2026-07-28"`。
   - 发起一次天文查询后查看后端容器日志：`docker logs --tail 50 astroagent-v16-backend-1`，应出现 `component: "mcp_client"` 与 `component: "mcp_server"` 的结构化 `mcp_tool_call` 日志行（不含查询全文与密钥）。
3. **切回直连模式**：在网页「Astronomy MCP 通道」关闭开关，或将私有环境文件中的 `ASTRONOMY_TOOL_TRANSPORT` 改为 `direct` 后更新 `backend`。确认状态胶囊显示 **直连模式**。

### 3.3 从容器独立启动 MCP Server（供外部本机客户端调用）

无需启动 PostgreSQL 或 FastAPI，即可复用容器镜像和挂载的 `backend_settings`（仅提取 `ADS_API_TOKEN` 与查询超时，自动剔除其他凭据）：

```powershell
docker compose --env-file .astroagent/container/deployment-v16.env `
  -f compose.yaml -f compose.plotting.yaml -f compose.identity.yaml `
  -f compose.compute.yaml -f compose.mcp.yaml `
  run --rm -T --no-deps backend mcp-server
```

或在无 Compose 秘密的独立容器环境通过环境变量注入：

```powershell
# 切勿将真实密钥写入命令行历史或共享文件；可在交互 shell 先设置 $env:ADS_API_TOKEN
docker run --rm -i --entrypoint python -e ADS_API_TOKEN `
  astroagent-backend:1.8.0 -m astroagent.mcp_server
```

## 4. 使用 MCP Inspector 独立验收

锁定验收客户端版本 `@modelcontextprotocol/inspector@2.16.0`：

### 4.1 Windows 本机启动

```powershell
# 如需测试 ADS 检索，先在当前终端注入环境变量（切勿写入命令行参数）
$env:ADS_API_TOKEN = "<your-ads-token>"
npx -y @modelcontextprotocol/inspector@2.16.0 --protocol-era modern `
  D:\astroagent-runtime\venv\Scripts\python.exe -m astroagent.mcp_server
```

在 Inspector 中确认：

1. 传输类型为 `STDIO`，服务名 `astroagent-astronomy`，版本 `1.8.0`，记录实际协商协议版本（目标 `2026-07-28`）。
2. `Tools` 列表仅包含三项工具：`query_simbad`、`search_ads`、`query_gaia`，均具备完整输入/输出 Schema 与只读注解。

### 4.2 可复制的 `tools/call` 参数样例

以下为三项独立调用示例；验收「SIMBAD → Gaia 名称联动」时，应以当次 `query_simbad` 返回的有效 `ra_deg`/`dec_deg` 填入 `query_gaia`：

```json
[
  {
    "name": "query_simbad",
    "arguments": {
      "object_name": "M45"
    }
  },
  {
    "name": "search_ads",
    "arguments": {
      "query": "abs:\"open clusters\"",
      "rows": 3,
      "start": 0
    }
  },
  {
    "name": "query_gaia",
    "arguments": {
      "mode": "cone",
      "ra_deg": 56.75,
      "dec_deg": 24.12,
      "radius_arcmin": 5,
      "limit": 20
    }
  }
]
```

## 5. 常见故障与排查

| 现象 / 错误码 | 原因 | 处理方式 |
| --- | --- | --- |
| `mcp_not_configured`（503） | 启用了 `ASTROAGENT_ASTRONOMY_TOOL_TRANSPORT=mcp`，但运行环境未安装 `mcp==2.3.0` | 执行 `python -m pip install -e ".[mcp]"` 或重建 1.8.0 后端镜像；若暂不启用 MCP 请切回 `direct` |
| `ads_not_configured`（`isError: true`，结果内保留） | 未在服务端环境或 `/run/secrets/backend_settings` 配置 `ADS_API_TOKEN` | 仅需 SIMBAD / Gaia 时可忽略；需检索 ADS 时通过进程环境或私有秘密文件注入 token 后重试 |
| `mcp_incompatible_protocol`（502） | MCP 服务端未声明 `2026-07-28`、`tools` 能力或工具清单与固定三项契约不符 | 核对后端镜像版本与依赖锁是否为 `1.8.0` / `mcp==2.3.0` |
| `mcp_process_exited`（502） | MCP 子进程意外退出或管道断开 | 同次状态不明查询不会自动重发，也不会静默切回直连；系统已回收异常连接，确认后端日志后手动发起新请求 |
| `mcp_response_too_large`（502） | 单条工具响应超过 `ASTROAGENT_MCP_MAX_MESSAGE_BYTES` | 缩小 `limit` / `rows` 或按需在允许范围内调高上限；结果不会被静默截断或改为空集 |
| `mcp_timeout`（504） | 超过启动或单调用总时限 | 核对上游网络与 `SIMBAD/ADS/GAIA_TIMEOUT_SECONDS`、`ASTROAGENT_MCP_CALL_TIMEOUT_SECONDS`；已回收阻塞子进程，请手动重试 |
| `mcp_pool_exhausted` / `mcp_busy`（503） | 并发查询占满执行槽且超过等待时限 | 稍后重试，或确认是否与聊天两轮并发上限冲突 |
| 外部客户端无法解析 JSON | 启动包装脚本向标准输出打印了普通文本 | 确认直接启动 `python -m astroagent.mcp_server` 且不在启动脚本中向 stdout 输出横幅或调试信息 |
