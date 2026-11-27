# Siderfolio V2.1.0 实施说明

**版本**：`2.1.0`　**日期**：2026-11-26　**基线**：`v2.0.7`（`6694ce4`）　**当前提交**：`5873ba8`（`v2.1.0`）  
**状态**：`v2.1.0` 本地测试与隔离库验收已通过并留证；云端发布/生产真实第三方外部 MCP 联调、目视复核与会后工作区增量收尾**待验收**

依据 [Siderfolio V2.1 开发文档](../../PROJECT_PLAN_V2.1.md) 与 [UI 设计规范](../../UI_DESIGN_SPEC.md)，本版本在不改变单 Agent 架构的前提下，交付了统一服务端工具目录、首批三个内置 `SKILL.md` 科研技能、受控外部 Streamable HTTP MCP 接入链路，以及对应的前端交互、个人设置、管理后台与运行追踪。

## 1. 交付清单

### M0 / M1 — 统一工具目录与内置科研技能系统
- **内置技能定义（`SKILL.md`）**：
  - `src/astroagent/skills_data/celestial-identification-field-query/SKILL.md`（天体识别与视场查询）
  - `src/astroagent/skills_data/astronomy-literature-curation/SKILL.md`（天文文献检索与整理）
  - `src/astroagent/skills_data/scientific-plotting-nbody-prep/SKILL.md`（科研绘图与 N 体实验准备）
  - `pyproject.toml` 在 `[tool.setuptools.package-data]` 中纳入 `skills_data/*/SKILL.md` 随包分发。
- **解析、渐进披露与匹配器**：
  - `src/astroagent/skill_schemas.py`、`src/astroagent/skills.py`：零第三方 YAML 依赖的严格 frontmatter 解析器（校验体积上限、NUL 字符、稳定 ID 与 SHA-256 摘要）；匹配阶段仅读取短描述、关键词与意图模式，最多命中一个技能后才向系统提示词注入正文；按「显式选择 > 自动匹配 > 普通对话」顺序执行，完整覆盖显式关闭（`none`）、个人关闭自动匹配（`auto_disabled`）、单技能停用（`disabled`）、多技能冲突（`ambiguous`）和所需工具不可用回退。
- **统一服务端工具目录**：
  - `src/astroagent/tool_schemas.py`、`src/astroagent/tool_catalog.py`：由同一份 `TurnToolCatalog` 生成模型绑定工具定义（`create_model`）、执行白名单与 `tool_manifest_sha256`，涵盖 6 项内置工具（`query_simbad`、`search_ads`、`query_gaia`、`prepare_nbody_simulation`、`prepare_scientific_plot`、`save_literature`）及管理员已批准的外部只读工具（`mcp__<server_id>__<remote_name>`，与内置名称严格隔离）。
  - `src/astroagent/agent.py`：在单轮执行中注入技能正文、校验参数与预算，并针对外部只读工具生成待用户确认的提案卡片（不自动外发）。

### M2 — 受控外部 Streamable HTTP MCP 与管理生命周期
- **服务端配置与客户端**：
  - `src/astroagent/config.py`、`src/astroagent/external_mcp_schemas.py`：默认关闭（`ASTROAGENT_EXTERNAL_MCP_ENABLED=false`）；仅接受运营者预配的固定 HTTPS 主机、端口与清洁路径（`ASTROAGENT_EXTERNAL_MCP_SERVERS_JSON`），禁止引用平台内部密钥环境变量前缀。
  - `src/astroagent/external_mcp_client.py`：实现 `2026-07-28` Streamable HTTP（JSON + SSE）握手、分页 `tools/list`（含游标循环与页数上限保护）、出站 DNS/IP 校验（拒绝内网、环回、链路本地、保留段及云元数据地址）、禁止重定向（`follow_redirects=False`）、严格字段白名单校验（拒绝未获准字段）、超时/响应大小/并发控制及返回数据收敛截断。
- **持久化、审批与确认**：
  - `src/astroagent/mcp_registry_store.py`：在 `public` schema 新增 `public.mcp_external_servers` 与 `public.mcp_external_tool_approvals`（通过 `AuthStore.install()` / `check()` 安装与核验）；仅允许批准 `readOnlyHint=true` 且非破坏性的工具，审批绑定 `definition_sha256`，定义变化后自动失效并阻断执行，所有管理写操作写入 `public.auth_audit`。
  - `src/astroagent/skill_store.py`：在每用户租户 schema（`aa_<hex>`）新增 `skill_meta`、`skill_preferences`、`external_mcp_confirmations`，按账号严格隔离个人技能偏好与外部查询确认记录；确认单绑定账号、项目、会话、轮次、`definition_sha256`、`arguments_sha256` 及有效期，支持幂等确认与取消。
- **后端路由与兼容**：
  - `src/astroagent/api/skills.py`：`GET /api/v1/skills`、`PUT /api/v1/skills/preferences`、`GET /api/v1/skills/tools`。
  - `src/astroagent/api/external_mcp.py`：`GET /api/v1/admin/mcp/servers`、`POST .../toggle`、`POST .../discover`、`POST .../tools/{remote_name}/approve`、`POST .../tools/{remote_name}/revoke`（管理写操作受现有 MFA + 近期重认证保护）。
  - `src/astroagent/api/conversations.py`、`src/astroagent/conversation_service.py`：`TurnRequest` 增加可选 `skill_id`（旧客户端省略兼容），新增 `POST /{conversation_id}/turns/{turn_id}/external-mcp/{confirmation_id}/confirm` 与 `/cancel`；在 `PreparedContext` 中携带已完成的外部只读查询摘要供后续追问引用。
  - 保留原有 `direct` / 本地 `stdio` Astronomy MCP 通道及三项固定契约不变。

### M3 — 运行追踪、OpenAPI 契约与前端界面
- **运行追踪扩展**：
  - `src/astroagent/trace_schemas.py`、`src/astroagent/trace_runtime.py`、`frontend/src/components/TurnTracePanel.vue`：`RunTrace` 新增 `skill_id`、`skill_title`、`skill_version`、`skill_mode`、`tool_manifest_sha256`；`RunSpan` 新增 `tool_external_mcp`、`external_mcp` 传输、`protocol_version`、`tool_source` 与 `mcp_transport` / `budget_exceeded` 错误类别。
- **OpenAPI 与类型同步**：
  - 版本号更新至 `2.1.0`（`pyproject.toml`、`src/astroagent/__init__.py`、`frontend/package.json`、`frontend/package-lock.json`），同步重新生成 `frontend/openapi.json`、`frontend/src/types/generated.ts` 并在 `frontend/src/types/index.ts` 统一导出。
- **前端组件与页面**：
  - `frontend/src/api/skills.ts`、`frontend/src/stores/skills.ts`、`frontend/src/api/index.ts`、`frontend/src/stores/workbench.ts`
  - `frontend/src/components/ComposerSkillPicker.vue`、`frontend/src/components/SkillDetailDialog.vue`、`frontend/src/components/ChatExternalMcpCard.vue`、`frontend/src/components/UiSelect.vue`、`frontend/src/views/App.vue`：查询工作台输入区提供「技能」选择器（统一承接绘图/N 体与科研技能，移除冗余独立快捷按钮），回答区精简阅读表面（技能命中方式与版本收进可展开 `TurnTracePanel`，打开/切换会话直接定位于底部无滑动动画），外部只读查询展示外发字段确认卡片，全站原生 `<select>` 统一替换为 `UiSelect` 毛玻璃顶层浮层。
  - `src/astroagent/literature_auth.py`：扩展口语化个人文献直接入库指令（如「把引用最高的 3 篇加入我的文献」）及引用/时间排序识别，继续严格拦截否定/假设/非个人库表述。
  - `frontend/src/components/SkillsSettings.vue`、`frontend/src/views/SettingsWorkspace.vue`：所有登录用户均可在「设置 → 技能与工具」管理自动匹配开关、单个内置技能启停并查看当前获准工具目录。
  - `frontend/src/components/AdminMcpPanel.vue`、`frontend/src/views/AdminWorkspace.vue`：后台新增「MCP 工具」管理区，支持服务启停、重新发现工具、核对定义摘要并逐项批准/撤销；遵循无独立「刷新」按钮与 `StatusNotice` 顶部浮层错误提示规范。

## 2. 数据库结构变化说明

所有新增结构均为**向后兼容的增量建表**，不修改或删除任何既有历史会话、项目、文献、绘图或 N 体计算表：
- 控制面（`public` schema）：`public.mcp_external_servers`、`public.mcp_external_tool_approvals` 及 `public.auth_meta` 键 `v21_mcp_schema=1`。
- 租户数据面（`aa_<hex>` schema）：`skill_meta`、`skill_preferences`、`external_mcp_confirmations`（按需首次写入自动建表，历史记录零迁移风险）。

## 3. 测试文件与验收状态

新增离线与 PostgreSQL 集成测试文件：
- `tests/test_skills_and_catalog.py`
- `tests/test_external_mcp.py`
- `tests/test_v21_postgres.py`

**`v2.1.0`（`5873ba8`）本地验收留证**：[20261126T015700Z 验收记录](../../test-records/v2.1.0/acceptance/20261126T015700Z/README.md)

- [x] 版本号一致（`2.1.0`）与 `python scripts/generate_frontend_types.py --check`（**已验证通过**）
- [x] Python `compileall`、`ruff check / format --check src tests scripts`、`pip check` 及离线 `pytest`（697 passed, 4 skipped, 0 failed）（**已验证通过**）
- [x] 独立测试库 PostgreSQL + 真实绘图（`pytest -m "postgres and not live"` + `scripts/ci_verify.py postgres`，98 passed, 0 skipped, 0 failed，含 `test_v21_postgres.py` 2/2 多账号隔离与审计）及计算沙箱 `scripts/ci_verify.py compute`（**已验证通过**）
- [x] 前端 `npm run typecheck`、`npm run lint`、`npm test`（47/47）、安全审计、`npm run build`、Playwright 浏览器套件（86 passed, 4 skipped）与邮件导航套件（12/12）（**已验证通过**）
- [x] 本机开发容器 `.\scripts\dev.ps1 -Action Update`（`astroagent-dev` 6 容器健康运行于 `http://127.0.0.1:5173`）（**已验证通过**）
- [ ] Linux 全量 Buildx 镜像与 `pip-audit` 校验（交由 GitHub Actions CI / Release 流水线，**待云端确认**）
- [ ] 桌面端与真机 390px 移动端目视复核（**待验收**）
- [ ] 生产环境真实第三方 HTTPS 外部 MCP 端点联调（默认关闭 `ASTROAGENT_EXTERNAL_MCP_ENABLED=false`，**待运营配置后验收**）

## 4. `v2.1.0` 会后工作区增量收尾（未提交，待验收）

在 `5873ba8` 之后，本机工作区补充了以下增量改进，**均尚未提交，也尚未重新运行自动化测试套件**：

- **文案一致性清理**：更新 `ComputeResultPanel.vue`、`ConversationSidebar.vue`、`PlotResultPanel.vue`、`ProjectOverview.vue`、`RagWorkspace.vue`、`WorkflowWorkspace.vue`，移除残留的旧输入区按钮指引与「请刷新核对」措辞（仅确认本机 Vite HMR 无报错，**待验收**）。
- **本地受控 HTTPS MCP 测试端点与端到端用例**：新增 `scripts/mock_external_mcp_server.py`、`tests/test_external_mcp.py::test_external_mcp_real_local_https_end_to_end` 及 [V2.1 运维手册](OPERATIONS.md) 第 4 节（**未运行 `pytest` / `ruff`，待验收**）。
- **N 体浏览器测试适配**：`frontend/tests/compute-browser/compute.spec.ts` 已将 4 处 `.selectOption(...)` 替换为 `chooseUiOption(...)`，但第 61 行仍点击已移除的 `button[name='N 体模拟']`，**尚未适配且未运行，待验收**。
