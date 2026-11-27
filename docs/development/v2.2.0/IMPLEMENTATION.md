# Siderfolio V2.2.0 实施说明｜Agent 长期记忆与上下文管理

**目标版本**：`v2.2.0`　**日期**：2026-11-27　**实施基线**：`v2.1.0`（`5873ba8`）  
**状态**：代码与契约实现已完成，本机预览已更新，自动化测试、隔离库迁移/回退演练及视觉验收**待用户安排验收**

依据 [Siderfolio V2.2 开发文档](../../PROJECT_PLAN_V2.2.md)、[UI 设计规范](../../UI_DESIGN_SPEC.md) 及用户交互精简调整，本版本在既有单 Agent、PostgreSQL + pgvector、租户私有 schema（`aa_<32-hex>`）和现有上下文字节预算（历史窗口 256 KiB、总模型消息 512 KiB）内，实现了默认开启的长期记忆功能、合成式记忆摘要、添加记忆入口、跨会话历史检索、超过 24 轮长对话摘要压缩、与 V2.1 科研技能匹配联动，以及取消管理员强制启用 MFA 的限制。

---

## 1. 交付清单（M0 → M3 及交互精简）

### M0 — 数据与权限契约
- [memory_schemas.py](../../../src/astroagent/memory_schemas.py)：
  - **默认开启主开关**：`MemoryPreferences` 默认 `auto_extract=True`、`cross_session_injection=True`、`history_retrieval=True`（附乐观锁修订号 `revision`）；前端收敛为单一「开启长期记忆」开关，同步控制三项能力。
  - **摘要视图契约**：新增 `MemorySummaryOverview` 与 `MemorySummarySection`，仅向用户返回按主题综合生成的叙事摘要（研究方向与背景、常用工具与偏好、科研项目脉络、补充信息），不暴露逐条原始记忆 ID 与记录列表。
  - **单范围约束**：`MemoryScope` 限定为 `global`（`project_id` 必须为 `None`）或 `project`（必须绑定已校验的自定义项目 UUID），避免跨空间重复生效。
  - **预算基线**：`MAX_INJECTED_MEMORIES=5`、`MAX_HISTORY_SNIPPETS=3`、`MAX_SUMMARY_BYTES=4096`（4 KiB）、`MAX_MEMORY_CONTEXT_BYTES=16384`（计入既有 512 KiB 总消息预算并按相关性低优先裁剪）。
  - **脱敏追踪模型**：`MemoryContextTrace` 与 `MemoryHistoryRef` 仅记录 ID、范围、条数、摘要覆盖首末轮次/字节、检索模式与降级原因，禁止将记忆正文、摘要或用户原文写入运行追踪与日志。
- 向后兼容扩展 [trace_schemas.py](../../../src/astroagent/trace_schemas.py)、[conversation_schemas.py](../../../src/astroagent/conversation_schemas.py) 与 [schemas.py](../../../src/astroagent/schemas.py)。

### M1 — 个人记忆闭环、提取安全防线与持久化
- [memory_extractor.py](../../../src/astroagent/memory_extractor.py)：
  - **敏感与越权过滤**：排除 API Key/Bearer Token/密码/邮箱/手机号/身份证号，拒绝试图绕过工具确认（文献自动入库、外部 MCP 自动外发、绘图/N 体自动执行或覆盖系统规则）的文本。
  - **显式直接保存与自动提取**：识别「记住我主要用 Python 做数据分析」等明确指令并返回 `MemorySaveReceipt`；记忆功能开启时，对用户亲自表述的 `turn.message` 执行有界规则提取并经安全过滤后自动汇入摘要（绝不读取文献、附件、工具返回或模型回答）。
  - **中英文词法检索与角色增强**：支持英文术语与中文 2–3 字短语切分，并针对「研究方向」「常用工具」「实验条件」「失败原因」等角色引用增强召回。
- [memory_store.py](../../../src/astroagent/memory_store.py) 与 [memory_service.py](../../../src/astroagent/memory_service.py)：
  - 租户私有 schema 增量建表、乐观修订号校验（冲突返回 `409`）、自动分类手工录入记忆并实时合成 `summary_overview()`。
  - **来源撤销联动**：删除会话（[conversation_service.py](../../../src/astroagent/conversation_service.py)）、移出会话或删除项目（[projects.py](../../../src/astroagent/projects.py)）时自动清理摘要与向量，并将受影响的派生记忆标记 `source_missing` / `source_moved` 且即时退出注入与摘要展示。

### M2 — 长对话摘要压缩与跨会话历史检索
- [context.py](../../../src/astroagent/context.py) 与 [agent.py](../../../src/astroagent/agent.py)：
  - 超过 24 轮时对移出窗口的已完成轮次生成 ≤ 4 KiB 的结构化摘要（保留目标条件、SIMBAD/Gaia/ADS/N 体/绘图关键单位与原轮次编号，缓存按 `source_sha256` 与 `turn_revisions` 校验并在源轮次变更时失效）；不修改原始会话与导出数据。
  - 跨会话历史检索严格按服务端推导的账号与项目边界筛选（个人空间仅个人历史，项目空间仅同项目历史），全部命中标注「历史」并提供原轮次跳转定位。
  - 上下文优先级遵循「系统安全规则 > 本轮用户指令与附件 > 当前项目指令与知识库 > 近期 24 轮窗口 > 较早摘要 > 相关记忆与历史片段」；预算紧张时按「历史片段 → 低相关记忆 → 摘要」依次裁剪并回退原窗口，在 `RunTrace` 与 `ContextRecord` 记录降级原因。

### M3 — 极简设置界面、可选 pgvector 语义召回与技能联动
- [skills.py](../../../src/astroagent/skills.py)：在技能意图评分中接入已筛选的 `memory_hint`（仅辅助已有正向意图的技能，防止无关记忆劫持普通对话），同步在 `MemoryContextTrace.skill_assisted_by_memory` 记录协同状态。
- [memory_service.py](../../../src/astroagent/memory_service.py)：复用 `LocalEmbedder`（固定模型 SHA-256 与维度）与 `memory_vectors` 提供可选 pgvector 语义召回；当嵌入模型未配置、核验失败或索引未就绪时无缝回退至 PostgreSQL 词法检索并记录降级状态。
- 后端 REST API：[api/memory.py](../../../src/astroagent/api/memory.py) 精简为 4 个接口（`GET /api/v1/memories/summary`、`GET /api/v1/memories/preferences`、`PUT /api/v1/memories/preferences`、`POST /api/v1/memories`），不暴露逐条原始记忆查询、编辑、删除与候选列表接口；同步生成 [openapi.json](../../../frontend/openapi.json) 与 [generated.ts](../../../frontend/src/types/generated.ts)。
- 前端界面：
  - [api/memory.ts](../../../frontend/src/api/memory.ts)、[stores/memory.ts](../../../frontend/src/stores/memory.ts)
  - [MemorySettings.vue](../../../frontend/src/components/MemorySettings.vue) 接入 [SettingsWorkspace.vue](../../../frontend/src/views/SettingsWorkspace.vue)（「设置 → 长期记忆」，所有已登录用户可见）：仅保留单一「开启长期记忆」开关（默认开启）与「记忆摘要」卡片，支持弹窗「添加记忆」，不展示逐条原始记忆列表
  - [MemoryReceiptCard.vue](../../../frontend/src/components/MemoryReceiptCard.vue) 接入 [App.vue](../../../frontend/src/views/App.vue)
  - [TurnTracePanel.vue](../../../frontend/src/components/TurnTracePanel.vue) 展示脱敏记忆条数、检索模式、摘要覆盖轮次、降级提示与跨会话 `[历史]` 原轮次跳转链接

### 补充调整 — 取消管理员强制开启 MFA 限制
- 保留 TOTP MFA 作为所有账号（含管理员）的可选安全加固能力；若管理员未开启 MFA，可直接进入工作台、设置页、模型配置与管理员控制台，执行敏感写操作时仍需 5 分钟内密码再次验证（若已开启 MFA，则继续同时要求验证码或恢复码）。
- 涉及文件：[auth_access.py](../../../src/astroagent/auth_access.py)、[api/admin.py](../../../src/astroagent/api/admin.py)、[api/model_providers.py](../../../src/astroagent/api/model_providers.py)、[api/auth.py](../../../src/astroagent/api/auth.py)、[identity-state.ts](../../../frontend/src/identity-state.ts)、[SettingsWorkspace.vue](../../../frontend/src/views/SettingsWorkspace.vue)、[AccountWorkspace.vue](../../../frontend/src/views/AccountWorkspace.vue)、[AdminWorkspace.vue](../../../frontend/src/views/AdminWorkspace.vue)、[WorkspaceHeader.vue](../../../frontend/src/components/WorkspaceHeader.vue)、[TurnTracePanel.vue](../../../frontend/src/components/TurnTracePanel.vue) 及 [test_identity_postgres.py](../../../tests/test_identity_postgres.py)。

---

## 2. 数据库结构变化说明（向后兼容增量建表）

不修改 `public.*` 控制面表，不修改既有历史会话/项目/文献/RAG/计算表，也不改动 `astroagent_meta.schema_version = 6`。仅在各账号私有 schema（`aa_<32-hex>`）新增以下 6 张 `CREATE TABLE IF NOT EXISTS` 表，关闭记忆功能时既有数据保留但不再学习或向模型发送：

| 表名 | 用途 | 清理/撤销约束 |
| --- | --- | --- |
| `memory_meta` | 记忆子模块版本标记（`version = 1`） | 仅版本号 |
| `memory_preferences` | 账号级记忆功能开关与修订号 | 默认开启 |
| `memories` | 全局个人与项目长期记忆记录 | 删除/暂停/替代即时移除对应向量与摘要引用 |
| `memory_candidates` | 内部候选记录表（兼容保留） | 绝不参与模型上下文注入 |
| `memory_vectors` | 可选 pgvector 记忆向量（固定模型哈希与维度） | `REFERENCES memories(id) ON DELETE CASCADE` |
| `conversation_summaries` | 超过 24 轮的长对话派生摘要缓存（≤ 4 KiB） | `REFERENCES conversations(id) ON DELETE CASCADE` |

`PostgresRepository._used(db)` 已纳入 `memory_store.used(db)` 计入租户存储预算。

---

## 3. UI 设计规范审查清单

- [x] 导航、标题与操作位置一致；无独立「刷新」按钮（进入页面与写操作后自动同步）。
- [x] 下拉选择使用 `UiSelect`（零原生 `<select>`），全部错误提示使用 `StatusNotice` 顶部浮层，操作反馈使用 `SuccessToast`。
- [x] 使用 `workspace-theme.css` 共用变量与 `.ui-*` 原语，添加记忆弹窗采用 `<dialog class="project-dialog">` 居中毛玻璃样式。
- [x] 设置页仅呈现开关、合成记忆摘要与添加记忆入口，不暴露逐条原始记忆；运行追踪仅展示脱敏元数据与跳转链接。
- [ ] 宽屏（1440px）、常规桌面（1280px）、紧凑桌面（1024px）、平板（768px）与移动端（390px）实机视觉与键盘可达性核对（**待验收**）。

---

## 4. 新增/更新测试文件与待验收事项

测试文件（遵循开发阶段不主动跑测规范，**尚未执行，待用户安排验收**）：
- [tests/test_memory_core.py](../../../tests/test_memory_core.py)（离线单测：默认开启、可选分类与单范围约束、直接保存与敏感/越权过滤、中文研究方向召回、>24 轮摘要与预算裁剪、技能协同与权限不绕过）
- [tests/test_memory_postgres.py](../../../tests/test_memory_postgres.py)（隔离 PostgreSQL + 多账号/多项目集成测试：`@pytest.mark.identity`、`@pytest.mark.postgres`，涵盖摘要接口、禁止逐条查看接口、主开关启停与来源撤销）
- [tests/test_identity_postgres.py](../../../tests/test_identity_postgres.py)（已同步更新管理员可选 MFA 边界断言）
- [frontend/tests/compute-browser/compute.spec.ts](../../../frontend/tests/compute-browser/compute.spec.ts)（Post-`v2.1.0` 收尾：已适配当前 v2.1+ 工作台交接入口与 `ComputeResultPanel` / `UiSelect`）

待验收检查项（由用户明确安排本机/隔离库验收时执行并留证至 `docs/test-records/v2.2.0/`）：
1. 后端静态检查与离线单测：`python -m ruff check src tests scripts`、`python -m ruff format --check src tests scripts`、`python -m pytest -q`
2. 隔离 PostgreSQL 验收：`pytest -m "postgres and not live"`（含 `tests/test_memory_postgres.py`、`tests/test_identity_postgres.py` 与旧版本数据库升级/备份/回退演练）
3. 前端静态检查、单测与构建：在 `frontend/` 执行 `npm run typecheck`、`npm run lint`、`npm test`、`npm run build`
4. 浏览器端到端与视觉验收：`npm run test:browser`、独立计算栈 `compute.spec.ts`，以及桌面端 / 390px 移动端目视核对
