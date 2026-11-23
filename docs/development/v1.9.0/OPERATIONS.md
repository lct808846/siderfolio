# AstroAgent V1.9.0 部署、升级与运维说明

**版本**：`1.9.0`　**日期**：2026-11-22

本文说明 V1.9.0 在既有 V1.6 身份认证、V1.7 计算任务与 V1.8 MCP 容器部署基础上的增量变更、数据保护与回滚方式。原有身份配置与私钥要求仍以 [V1.6 运维说明](../v1.6.0/OPERATIONS.md) 与 [V1.8 MCP 运维说明](../v1.8.0/OPERATIONS.md) 为准。

## 1. 增量数据库表与非破坏式升级

- V1.9.0 **不修改** 现有 `astroagent_meta.schema_version = 6`，不删除或重写任何 V1.8 会话、项目、知识库、身份或计算记录。
- 每个登录账号在其隔离 PostgreSQL schema（`aa_<32hex>`）内按需自动初始化两类增量表：
  - **个人文献库**：`literature_meta`、`literature_items`（`UNIQUE(provider, bibcode)`）、`literature_save_receipts`（`UNIQUE(client_request_id, scope)`）。
  - **运行追踪**：`run_trace_meta`、`run_traces`（单账号保留上限 300 条、30 天自动清理）。
- 账号数据备份脚本 `scripts/identity_backup.py` 通过按 schema 导出自动包含上述新表；项目 ZIP 导出保持既有项目业务范围，不混入全局个人文献库。

## 2. 新增可选服务端环境变量

| 变量名 | 默认值 | 说明 |
| --- | --- | --- |
| `ASTROAGENT_MODEL_PRICING_JSON` | 空 | 可选 JSON 映射（例如 `{"deepseek-chat":{"input_per_1m":0.28,"output_per_1m":0.42,"currency":"USD","version":"2026-11"}}`）。配置后运行追踪将展示带版本标识的费用估算；未配置或模型未上报 token 时诚实显示「费用未知 / 用量未报告」，绝不捏造。 |

切勿将任何 API 密钥或价目私钥放入 `VITE_*` 前端变量。

## 3. 容器构建与滚动更新

`scripts/containers.ps1` 已自动叠加 `compose.v19.yaml`（将 `backend`、`frontend`、`ingress` 镜像固定为 `:1.9.0`）。保留既有 `.astroagent/container/deployment-v16.env` 与全部数据卷执行：

```powershell
.\scripts\containers.ps1 -Action up
```

或仅更新本次变更的三个服务而不触碰 `postgres` / `ollama` / `compute-worker` / `plot-executor`：

```powershell
docker --host npipe:////./pipe/docker_engine compose `
  --env-file .astroagent\container\deployment-v16.env `
  -f compose.yaml -f compose.plotting.yaml -f compose.identity.yaml `
  -f .astroagent\container\compose-v16-shared-model.yaml `
  -f compose.compute.yaml -f compose.mcp.yaml -f compose.v19.yaml `
  --profile compute up -d --build --no-deps backend frontend ingress
```

检查健康状态：

```powershell
docker --host npipe:////./pipe/docker_engine ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
```

## 4. 安全与隔离核对项

- 独立 MCP 服务（`astroagent.mcp_server`）保持严格 3 个只读天文工具（`query_simbad`、`search_ads`、`query_gaia`），绝不暴露 `save_literature`。
- 无状态 `POST /api/v1/chat` 不绑定 `save_literature`，仅登录会话内受服务端 `SavePermit` 授权时才允许直接入库。
- 运行追踪排除提示词全文、推理过程、论文摘要、附件原文、个人笔记、凭据及原始堆栈。

## 5. 回滚说明

如需回退至 `v1.8.0`，移除 `-f compose.v19.yaml` 重新启动 `backend`、`frontend`、`ingress` 即可。V1.9 增量表位于独立表名下，不阻塞 V1.8 运行；切勿在未授权情况下清空数据库或删除卷。
