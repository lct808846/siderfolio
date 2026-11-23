# AstroAgent V1.9.0 实施说明

**版本**：`1.9.0`　**日期**：2026-11-22　**状态**：源码已完成并更新部署容器，功能与视觉验收**待验收**

依据 [V1.9 开发文档](../../PROJECT_PLAN_V1.9.md) 与 [UI 设计规范](../../UI_DESIGN_SPEC.md)，本轮完成 M0–M4 全部开发交付。

## 1. 交付清单

### M1 — 顶部栏导航与个人天文文献库
- **后端模型与存储**：
  - `src/astroagent/literature_schemas.py`：文献条目、分页列表、批量状态查询、手动入库、标签/备注修订、服务端入库回执与 DOI 校验模型。
  - `src/astroagent/literature_store.py`：按账号 schema 隔离的 PostgreSQL 仓储（`literature_items`、`literature_save_receipts`），实现 `ON CONFLICT (provider, bibcode) DO NOTHING` 并发去重、保留既有标签/备注、同事务幂等回执、乐观锁修订号校验及来源会话删除后保留条目可读性（动态计算 `origin.source_available`）。
  - `src/astroagent/literature_service.py` 与 `src/astroagent/api/literature.py`：提供 `GET/POST /api/v1/literature/items`、`GET /api/v1/literature/items/status`、`GET/PATCH/DELETE /api/v1/literature/items/{item_id}`；导入/未验证批次入库前强制通过 ADS 核实。
- **前端界面**：
  - `frontend/src/components/WorkspaceHeader.vue`：版本更新为 `1.9`，在「查询工作台」右侧新增「文献管理」全局导航入口（支持桌面与 390px 窄屏、键盘访问、`aria-current="page"`，返回工作台时恢复最近会话与项目路径）。
  - `frontend/src/views/LiteratureWorkspace.vue`（路由 `/literature`、`/literature/:itemId`）：双栏响应布局，严格分区呈现 **ADS 原始书目与摘要快照**、**入库来源与模型说明**（与 ADS 原文清晰隔离，原对话删除后给出非破坏提示）以及 **个人标签与阅读备注**（支持 409 并发冲突刷新提示与原生 `<dialog>` 移除确认）。
  - `frontend/src/components/ResultPanel.vue`：ADS 结果列表标出 `#1..#N` 稳定序号，批量检查并展示「已在文献库 / 查看详情 ↗」或「加入文献库」按钮，与 Agent 共享同一后端服务。

### M2 — 对话检索 ADS 与受权直接入库
- `src/astroagent/literature_auth.py`：仅从当前轮用户原始消息非引号区段解析一次性 `SavePermit`，拒绝否定语句、假设/疑问句、多批次含糊指代及摘要/附件/历史中的注入文本。
- `src/astroagent/agent.py` & `src/astroagent/context.py`：仅在登录会话 `converse()` 绑定内部工具 `save_literature`（无状态 `/api/v1/chat` 与独立 `mcp_server.py` 均不暴露），模型只提交可核对批次与序号/bibcode 引用。
- `src/astroagent/conversation_service.py`：在 `finally` 与轮次读取（`enrich_turn`）阶段从数据库恢复已提交回执，确保末段失败或断线刷新后仍以服务端落库状态为准。
- `frontend/src/components/LiteratureReceiptCard.vue`：在会话轮次内依据服务端回执渲染逐条入库状态与直达文献详情链接。

### M3 — 运行追踪、故障定位与固定评估集
- `src/astroagent/trace_schemas.py`、`src/astroagent/trace_store.py`、`src/astroagent/trace_runtime.py`、`src/astroagent/mcp_client.py`、`src/astroagent/model_client.py`：
  - 记录脱敏结构化 `RunTrace`（单账号有界保留 300 条 / 30 天），覆盖 `rag_context`、模型轮次（实报 token + 可选价目估算）、SIMBAD/ADS/Gaia（区分 `direct` / `mcp` 及 MCP `correlation_id`、截断和归类错误码）、`save_literature`、N 体与绘图方案生成。
  - 排除提示词全文、推理过程、摘要、附件原文、笔记、密钥和原始堆栈；追踪写入失败降级为 `trace_status="unavailable"`，不影响回答与文献回执。
- `src/astroagent/compute_schemas.py`、`src/astroagent/compute_tasks.py`、`src/astroagent/api/compute.py`、`frontend/src/components/ComputeResultPanel.vue`：计算详情新增实测 `timing`（排队等待、实际执行、总耗时，未采集时显式标注）与状态时间线。
- `frontend/src/components/TurnTracePanel.vue`：会话轮次内可展开的运行详情面板，支持一键跳转到对应数据结果或文献管理。
- `docs/development/v1.9.0/evaluation-cases.json` 与 `scripts/evaluate_v19.py`：冻结 5 类科学基准场景与阈值，支持离线/隔离在线评估及 V1.8 vs V1.9 对照报告生成。

### M4 — 契约同步、性能优化、部署配置与待验收项
- 更新版本号至 `1.9.0`，同步再生 `frontend/openapi.json` 与 `frontend/src/types/generated.ts`。
- **加载与会话切换性能优化**：
  - 新增单请求整会话接口 `GET /api/v1/conversations/{conversation_id}/bundle`（在单次数据库查询连接内批量加载会话、全部轮次、文献入库回执与运行追踪，消除原 `1 + N` 轮次瀑布请求）。
  - 为 `AuthStore` 与每租户 `PostgresRepository` 增加隔离连接复用池，并将 `auth_sessions.last_seen` 节流至 60 秒窗口更新，消除并发请求行锁竞争与频繁建连开销；在 `LocalAccess` 按环境指纹缓存 `LocalSettings`。
  - `containers/frontend/ingress.mjs` 与 `frontend/server.mjs` 启用 HTTP Keep-Alive 代理池、10 秒 `ingress` DNS 缓存、静态资源内存缓存与 gzip 压缩，并为内容哈希 `/assets/*` 资源启用 `immutable` 缓存（`index.html` 与 `/api/*` 保持 `no-store`）。
  - 前端对次级工作区按需代码分割（`defineAsyncComponent`），`identityGuard` 在已认证 30 秒新鲜窗口内无阻塞切页，`useWorkbench` 增加按账号隔离的内存会话缓存与侧边栏悬停预取。
- 新增 `compose.v19.yaml`、更新 `scripts/containers.ps1` 与 [OPERATIONS.md](OPERATIONS.md)。
- **待验收项**（开发期按仓库约定不主动运行自动化测试和功能验收）：
  - [ ] 桌面与 390px 窄屏视觉检查及 6 套日/夜主题对比度核查（**待验收**）
  - [ ] 后端 `pytest`、Ruff、前端 `typecheck` / `lint` / `vitest` / Playwright 浏览器测试（**待验收**）
  - [ ] 双账号隔离、并发去重、流式断线恢复、MCP 只读面与实时评估报告留证（**待验收**）
