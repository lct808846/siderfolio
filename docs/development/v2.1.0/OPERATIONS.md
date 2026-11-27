# Siderfolio V2.1 运维与外部 MCP 配置说明

V2.1.0 在保留既有内置工具（SIMBAD / ADS / Gaia / 绘图 / N 体 / 文献保存）及 V1.8 本地 `stdio` Astronomy MCP 通道的基础上，新增了**默认关闭**的受控外部 Streamable HTTP MCP 接入链路。

## 1. 环境变量与安全基线

外部 MCP 服务清单与凭据仅能由运营者在服务端私有配置中预配，**严禁**写入 `VITE_*` 前端变量或普通用户可编辑配置。

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ASTROAGENT_EXTERNAL_MCP_ENABLED` | `false` | 外部 MCP 总开关。为 `false` 时系统不加载任何外部服务，不发起任何外部 MCP 请求，所有内置工具与本地 `stdio` MCP 正常工作。 |
| `ASTROAGENT_EXTERNAL_MCP_SERVERS_JSON` | `[]` | 运营者预配的外部只读 Streamable HTTP MCP 服务 JSON 数组（见下方示例）。 |
| `ASTROAGENT_EXTERNAL_MCP_MAX_CALLS_PER_TURN` | `2` | 单轮对话中允许提出的外部 MCP 查询上限（范围 `1–4`）。 |

### `ASTROAGENT_EXTERNAL_MCP_SERVERS_JSON` 结构示例

```json
[
  {
    "id": "cds_readonly",
    "title": "CDS 只读星表检索",
    "description": "受控外部天文星表只读查询服务",
    "scheme": "https",
    "host": "mcp.astro-example.org",
    "port": 443,
    "path": "/mcp",
    "protocol_version": "2026-07-28",
    "auth_header": "Authorization",
    "auth_env_var": "EXT_MCP_CDS_TOKEN",
    "auth_scheme": "Bearer",
    "connect_timeout_seconds": 5,
    "discover_timeout_seconds": 10,
    "call_timeout_seconds": 15,
    "max_request_bytes": 65536,
    "max_response_bytes": 262144,
    "max_concurrency": 2,
    "cache_ttl_seconds": 300
  }
]
```

### 强制安全约束

1. **固定 HTTPS 端点**：仅允许 `scheme="https"`，禁止路径携带查询串、片段或 `..`。
2. **禁止内网与云元数据地址**：发起发现与调用前均校验最终 DNS/IP，自动阻断 `localhost`、环回地址、`10/8`、`172.16/12`、`192.168/16`、链路本地、保留段及云元数据地址（如 `169.254.169.254`、`metadata.google.internal`），并禁用 HTTP 重定向（`follow_redirects=False`）。
3. **凭据引用隔离**：`auth_env_var` 只能引用专用的外部 MCP 环境变量名，服务端自动拒绝 `DEEPSEEK_`、`OPENAI_`、`ANTHROPIC_`、`GEMINI_`、`ASTROAGENT_DATABASE_`、`ASTROAGENT_AUTH_`、`ASTROAGENT_PROXY_`、`ASTROAGENT_PLOT_`、`PG`、`SMTP_` 等平台内部凭据前缀。
4. **只读工具与定义摘要锁定**：首版仅允许管理员批准声明 `readOnlyHint=true` 且非破坏性的工具；工具定义发生变化时自动标记为失效并暂停调用，需管理员复核后重新批准。
5. **逐轮外发字段确认**：外部工具不自动执行，调用前在对话卡片展示目标服务、主机及本次精确外发字段，由用户点击确认后执行；完整会话、账号凭据、项目 RAG 原文与原始附件不会外发。

## 2. 管理员启停与审批流程

1. 运营者在服务端私有配置中设置 `ASTROAGENT_EXTERNAL_MCP_ENABLED=true`、`ASTROAGENT_EXTERNAL_MCP_SERVERS_JSON` 及对应凭据环境变量，重启后端服务。
2. 已通过 MFA 验证的管理员登录网页，进入 **「管理后台 → MCP 工具」**（`/admin?section=mcp`）。
3. 针对目标预配服务点击 **「重新发现工具」**，服务端执行 `2026-07-28` 握手与分页 `tools/list`。
4. 逐项核对工具名称、说明、只读声明、输入字段与 `definition_sha256`，仅对确认安全的只读工具点击 **「批准」**。
5. 切换该服务状态为 **启用**，获准工具即进入用户的工具目录与对话可用清单。
6. 如需紧急止损，可随时在后台点击 **「撤销」** 单个工具、**「停用服务」**，或将 `ASTROAGENT_EXTERNAL_MCP_ENABLED` 切回 `false`；历史会话中的已执行记录仍保持可读。

## 3. 数据库升级与回退说明

> **注意**：正式库（GCP 生产实例）的任何结构升级均须按[开发与发布手册](../../DEVELOPMENT_AND_RELEASE.md)单独核对并获得明确授权后执行。

### 升级影响（纯增量、可逆）
- 控制面（`public`）：`AuthStore.install()` 会创建 `public.mcp_external_servers`、`public.mcp_external_tool_approvals`，并在 `public.auth_meta` 写入 `v21_mcp_schema='1'`。
- 租户面（`aa_<hex>`）：用户首次保存技能偏好或生成外部 MCP 确认单时自动创建 `skill_meta`、`skill_preferences`、`external_mcp_confirmations`。
- 不修改任何现有表结构与历史数据。

### 回退步骤（独立测试库验证后执行）
1. 立即停用功能（无需删表）：设置 `ASTROAGENT_EXTERNAL_MCP_ENABLED=false` 并回滚后端/前端镜像至 `v2.0.7`；历史对话与运行追踪保持正常读取。
2. 如需彻底清理测试环境新增控制面表（仅限已核对的独立库）：
   ```sql
   DROP TABLE IF EXISTS public.mcp_external_tool_approvals;
   DROP TABLE IF EXISTS public.mcp_external_servers;
   DELETE FROM public.auth_meta WHERE key = 'v21_mcp_schema';
   ```

## 4. 独立受控 HTTPS 测试端点验收

仓库内置了无外部依赖的本地自签名 HTTPS Streamable HTTP 测试服务端 [mock_external_mcp_server.py](../../../scripts/mock_external_mcp_server.py)，用于离线/隔离环境验收 `2026-07-28` 握手、分页 `tools/list`（含 SSE）、Bearer 鉴权、定义变更、协议不兼容、302 重定向阻断、超时与超大输出收敛：

```powershell
# 独立启动本机受控 HTTPS 测试端点（仅用于隔离测试，切勿用于生产）
python scripts/mock_external_mcp_server.py --port 8443 --token synthetic-ext-token
```

对应的自动化 TLS 端到端用例位于 `tests/test_external_mcp.py::test_external_mcp_real_local_https_end_to_end`（同时验证默认生产出站策略仍会拒绝 `127.0.0.1`）。

## 5. 故障排查

- **`external_mcp_disabled`**：确认服务端环境已设置 `ASTROAGENT_EXTERNAL_MCP_ENABLED=true` 且已重启后端。
- **`mcp_egress_blocked`**：目标主机或其 DNS 解析结果落入内网、环回或云元数据网段；请核对 DNS 与白名单出口。
- **`mcp_incompatible_protocol`**：远端未按 `2026-07-28` 协议握手、未声明 `capabilities.tools` 或缺少 `serverInfo.name`。
- **`mcp_definition_changed` / `tool_definition_changed`**：远端工具 Schema 或说明发生变更，请在「管理后台 → MCP 工具」重新发现并复核后再次批准。
- **结构化日志**：外部 MCP 客户端日志以 `component: "external_mcp_client"` 输出到后端标准错误流，仅含 `correlation_id`、`tool`、`protocol_version`、`duration_ms`、`result_status`、`returned_count`、`error_code`，不包含密钥或完整请求内容。
