# Siderfolio v2.1.0 本地测试与验收记录

- **目标版本**：`v2.1.0`（基于 `v2.0.7` / `6694ce4ffadc30b6fb8d3f065025594f9b24fde1`）
- **验收时间（UTC）**：`2026-11-26T01:57:00Z`
- **交付范围**：
  1. **统一服务端工具目录与三个内置 `SKILL.md` 科研技能**：新增 `src/astroagent/skills.py`、`skill_schemas.py`、`skill_store.py`、`skills_data/*/SKILL.md`、`tool_catalog.py`、`tool_schemas.py`、`api/skills.py`，实现单 Agent 渐进披露技能匹配（显式选择 > 自动匹配 > 普通对话）、`TurnToolCatalog` 单一真源工具定义与执行白名单、以及 `RunTrace`/`RunSpan` 技能与外部工具追踪扩展。
  2. **受控外部 Streamable HTTP MCP 接入链路（默认关闭）**：新增 `src/astroagent/external_mcp_client.py`、`external_mcp_schemas.py`、`mcp_registry_store.py`、`api/external_mcp.py`，支持 `2026-07-28` 握手与分页发现、固定 HTTPS 端点与出站私网/元数据地址阻断、凭据前缀隔离、管理员 MFA 逐项只读工具批准/定义摘要锁定与撤销、以及用户逐轮外发字段确认与幂等执行。
  3. **前端工作台、个人设置、管理后台与全站 `UiSelect` 统一**：新增 `ComposerSkillPicker.vue`、`SkillDetailDialog.vue`、`SkillsSettings.vue`、`ChatExternalMcpCard.vue`、`AdminMcpPanel.vue`、`UiSelect.vue`，替换全站原生 `<select>` 为顶层毛玻璃浮层 `UiSelect`，同步更新 `AGENTS.md`、`docs/UI_DESIGN_SPEC.md`、`docs/ROADMAP.md`、`docs/PROJECT_PLAN_V2.1.md` 与 `docs/development/v2.1.0/`。
  4. **数据库纯增量建表（已获用户明确授权）**：控制面 `public.mcp_external_servers`、`public.mcp_external_tool_approvals` 及 `public.auth_meta` 键 `v21_mcp_schema='1'`；租户面 `skill_meta`、`skill_preferences`、`external_mcp_confirmations`。全部通过 `CREATE TABLE IF NOT EXISTS` 幂等创建，不修改任何历史表结构与现有数据。

## 本地验收汇总

| 检查项 | 命令 / 环境 | 结果 | 说明 |
| --- | --- | --- | --- |
| 版本号与 OpenAPI 契约 | `pyproject.toml` / `__init__.py` / `package.json` / `package-lock.json` 一致性 + `python scripts/generate_frontend_types.py --check` | 通过 | 5 处版本号均为 `2.1.0`，OpenAPI 快照与 `frontend/src/types/generated.ts` 一致 |
| Python 编译与静态检查 | `compileall`、`ruff check src tests scripts`、`ruff format --check src tests scripts`、`pip check` | 通过 | 228 个文件格式一致，零 lint 警告，依赖无冲突 |
| Python 离线单测 | `pytest -m "not live and not postgres" -ra` | 697 passed, 4 skipped, 0 failed | 含 `test_skills_and_catalog.py`（9/9）、`test_external_mcp.py`（16/16）、`test_exports.py`（57/57）。跳过项：`test_knowledge.py:261,524`（显式夹具/256 MiB 磁盘验收）与 `test_linux_resource_limits.py:44,73`（仅 Linux） |
| 隔离 PostgreSQL + 真实绘图 | 临时 `pgvector/pgvector:0.8.7-pg16-bookworm`（`127.0.0.1:55432`）+ `astroagent-dev-plot-python:local` + `astroagent-dev-plot-gnuplot:local`；`pytest -m "postgres and not live" -ra` + `scripts/ci_verify.py postgres` | 98 passed, 0 skipped, 0 failed | 含新增 `test_v21_postgres.py`（2/2：跨账号技能偏好隔离、管理员外部 MCP 发现/只读审批/拒绝写入工具、跨用户 404/篡改 409/幂等重放、定义变更自动失效与审计记录）；未接触日常库 `astroagent_dev` |
| 数值计算沙箱验收 | `scripts/ci_verify.py compute`（`--network none --read-only --cap-drop ALL`） | 通过 | REBOUND（误差 `< 1e-8`）与 PeTar（误差 `< 1e-5`）圆轨道双星校验通过 |
| 前端静态检查、单测与审计 | `npm run typecheck`、`npm run lint`、`npm test`、`npm audit --omit=dev --audit-level=high`、`scripts/check_frontend_audit.py`、`npm run build` | 通过 | Vitest 10 文件 / 47 用例全通；零高危漏洞；生产构建成功（保留既有主包 >500 kB Vite 提示） |
| Playwright 浏览器套件 | `npm run test:browser`（Chromium + Edge） | 86 passed, 4 skipped, 0 failed | 跳过项：`container-live.spec.ts`（×2 浏览器）与 `knowledge.spec.ts:50`（×2 浏览器），均为需显式环境夹具的条件用例 |
| Playwright 邮件导航套件 | `npx playwright test --config playwright.mail-navigation.ts`（Chromium + Edge） | 12 passed, 0 failed | 跨站点击、激活确认、重置链接、两步登录流全通 |
| 本机开发容器更新 | `.\scripts\dev.ps1 -Action Update` | 通过 | `astroagent-dev` 全部 6 个容器健康运行于 `http://127.0.0.1:5173` |

## 首轮验收发现与修复记录

1. **历史快照导出兼容性（`src/astroagent/export_schemas.py`）**：`ChatResponse` 新增 `skill_resolution`、`external_mcp_proposals`、`external_mcp_results` 后，`ExportSnapshot` 严格模式误将其视为历史快照必填字段导致 `test_historical_v03_snapshots_remain_exportable` 失败；已将 3 个 V2.1 新字段加入历史可选字段白名单并重新同步 `frontend/openapi.json` 与 `frontend/src/types/generated.ts`。
2. **多技能正则得分上限对称化（`src/astroagent/skills.py`）**：`celestial-identification-field-query` 有 3 条正则而 `astronomy-literature-curation` 仅 2 条，导致同时包含 SIMBAD/Gaia 与 ADS/保存文献的双意图提问得分差为 2 未触发 `ambiguous`；已将正则加分统一封顶为 `min(pattern_hits * 2, 4)`。
3. **技能选择器加载竞态（`frontend/src/components/ComposerSkillPicker.vue`）**：`skillsStore.load()` 清空状态期间误触发 `enabledSkills` watcher 清除了 `/projects/:id/plotting` 预选的绘图技能与 `toolMode`；已加 `skillsStore.loaded` 守卫修复。
4. **前端 TypeScript 与 ESLint 修复**：修复 `AdminMcpPanel.vue` 8 处可选数组判空、`SkillDetailDialog.vue` 拼写错误 `toolsManifestSha256` -> `toolManifestSha256`，并将 `FeedbackPanel.vue`、`ProjectManageDrawer.vue`、`KnowledgeWorkspace.vue`、`WorkflowWorkspace.vue` 中模板内联 `as UiSelectOption<...>[]` 类型断言迁入 `<script setup>` 消除 `vue/no-parsing-error`。
5. **测试夹具与新版 UI 选择器对齐**：修复 `tests/test_skills_and_catalog.py`（同时校验 `openai_responses` `t["name"]` 与 `openai_chat` `chat_model.kwargs["tools"]`）、`tests/test_v21_postgres.py`（为 `client.fresh()` 绑定 `store`/`identity`、改用 `tenants.for_user` 及真实 UUID 轮次 `repository.reserve`），以及新增 `frontend/tests/browser/ui-select.ts` 将 7 份浏览器测试从原生 `<select>` / 旧快捷按钮更新至 `UiSelect` / `ComposerSkillPicker` / `ui-choice-card`。
6. **Python 格式与 Lint**：清理 `agent.py` 6 处未使用导入并修复 12 个文件的 Ruff 行宽与格式问题。

## 未在本地执行的检查（由云端 CI / 正式发布或后续人工验收覆盖）

- Linux 容器生产镜像全量 Buildx 校验（`backend`、`frontend`、`ingress`、`postgres`、`compute-worker`、`plot-executor`）及 `pip-audit` 由主分支 GitHub Actions `Tests` 与 `v2.1.0` `Formal release` 流水线执行。
- 生产环境外部 MCP 真实第三方 HTTPS 端点联调：生产默认 `ASTROAGENT_EXTERNAL_MCP_ENABLED=false`，待运营者配置实际外部 HTTPS 服务后再按 `docs/development/v2.1.0/OPERATIONS.md` 在管理后台逐项发现与审批。
- 桌面与真机移动端界面目视复核待发布上线后确认。
