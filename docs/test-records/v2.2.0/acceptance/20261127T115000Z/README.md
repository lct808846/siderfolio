# Siderfolio v2.2.0 本地测试与验收记录

- **目标版本**：`v2.2.0`（基于 `v2.1.0` / `5873ba8f78b57c3b6a9e88c2f03828dc6b9edcb7`）
- **验收时间（UTC）**：`2026-11-27T11:50:00Z`（北京时间 `2026-11-27 19:50:00`）
- **运行环境**：Windows 11 + Docker Desktop WSL2 Linux 引擎；Python `3.12.13`（`pytest 9.1.1`、`ruff`）；Node `v22.15.0`（生产容器与 GitHub Actions CI 使用 Node 24.x）。
- **验收范围**：
  1. Agent 长期记忆与上下文管理（默认开启主开关、合成记忆摘要、手工与显式直接保存、规则自动提取、超过 24 轮长对话摘要压缩、跨会话历史检索与原轮次引用、技能协同、脱敏运行追踪、租户私有 schema 增量 6 张表）。
  2. 多模态图片附件上传与后端 Pillow 安全净化重编码、邮件模板与 TOTP 品牌图标美化、工作台输入区精简与文案收尾。
  3. 自动发布更新日志生成（`scripts/release_assets.py notes` + `release.yml`）、仓库改名 `siderfolio` 生产迁移兼容、本地自签名 HTTPS External MCP 测试脚本，以及重写后的 `README.md` 与合成实机截图。

## 1. 本地验收汇总

| 检查项 | 命令 / 环境 | 最终结果 | 说明 |
| --- | --- | --- | --- |
| OpenAPI 与前端类型契约 | `python scripts/generate_frontend_types.py --check` | **通过** | `frontend/openapi.json`（`2.2.0`）与 `frontend/src/types/generated.ts` 同步一致 |
| Python 编译与静态检查 | `compileall`、`ruff check src tests scripts`、`ruff format --check src tests scripts`、`pip check` | **通过** | 237 个文件全部合规，零 lint 警告，依赖无冲突 |
| Python 离线单测 | `pytest -m "not live and not postgres" -ra --junitxml=outputs/v220-python.xml` | **710 passed, 4 skipped, 0 failed** | 含 `test_memory_core.py`（5/5）、`test_release_notes.py`（6/6）、`test_external_mcp.py`（17/17 含本地 HTTPS 端到端）、`test_exports.py`（57/57）、`test_v11_attachment_model_acceptance.py`（9/9）；跳过项为 `test_knowledge.py:261,524`（显式夹具/磁盘验收）与 `test_linux_resource_limits.py:44,73`（仅 Linux） |
| 隔离 PostgreSQL + 真实绘图 | 临时 `pgvector/pgvector:0.8.7-pg16-bookworm`（`127.0.0.1:55432`）+ 本地 Python/Gnuplot 绘图镜像；`pytest -m "postgres and not live" -ra --junitxml=outputs/v220-postgres.xml` + `scripts/ci_verify.py postgres` | **100 passed, 0 skipped, 0 failed** | `PostgreSQL coverage: 100 passing cases`（EXIT=0）；覆盖 `test_memory_postgres.py`（2/2）、`test_v21_postgres.py`（2/2）、`test_identity_postgres.py`（35/35）、RAG/计算/绘图/反馈等全量隔离库测试；未触碰 `astroagent_dev` |
| 科学计算沙箱验收 | `docker run --rm --network none --read-only --cap-drop ALL ... /ci_verify.py compute`（`astroagent-dev-compute:9562da4101e2933158e4`） | **通过** | REBOUND（误差 `< 1e-8`）与 PeTar（误差 `< 1e-5`，相对能量误差 `4.36e-14`）圆轨道双体校验通过 |
| 前端静态检查、单测、审计与构建 | `npm run typecheck`、`npm run lint`、`npm test`、`npm audit --omit=dev --audit-level=high`、`scripts/check_frontend_audit.py`、`npm run build` | **通过** | Vitest `10/10` 文件 `47/47` 用例通过；生产与全量依赖审计零高危阻断；生产构建成功 |
| Playwright 邮件导航套件 | `npx playwright test --config playwright.mail-navigation.ts`（Chromium + Edge） | **12 passed, 0 failed** | 跨站邮件导航、激活/重置确认与两步登录全通 |
| Playwright 主浏览器套件 | `npm run test:browser` + 目标复跑（Chromium + Edge） | **86 passed, 4 skipped, 0 failed** | 首轮 82 passed / 4 failed（2 个用例仍引用已移除的 `ComposerSkillPicker`）；适配 `current-changes.spec.ts` 与 `plot-acceptance.spec.ts` 后 8/8 复测全通；跳过项为 `container-live.spec.ts`（×2）与 `knowledge.spec.ts:52`（×2） |
| README 实机截图视觉核查 | 隔离合成数据渲染 4 张实机页面并逐张检查 | **通过** | 桌面工作台（含真实 Matplotlib 渲染 M45 色—星等图）、个人文献库、记忆设置与 390px 移动端均零报错、零隐私信息 |

## 2. 首轮验收发现并修复的真实缺陷与问题

1. **PostgreSQL 参数化空值缺陷（真实生产阻断 bug，已修复）**：`src/astroagent/memory_service.py` 中 4 处 `AND (project_id=? OR (? IS NULL AND project_id IS NULL))` 在 PostgreSQL 下触发 `IndeterminateDatatype`，导致全局记忆写入/直接保存/自动提取返回 `503`；已抽离 `_active_scope_items()` 按 `project_id is None` 显式分支查询，隔离 PostgreSQL 100/100 全部通过。
2. **历史快照导出兼容性回归（已修复）**：`src/astroagent/export_schemas.py` 在 `ChatResponse` 历史快照可选字段白名单中补入 `memory_receipts` 并同步 OpenAPI/前端类型，恢复 `test_historical_v03_snapshots_remain_exportable` 通过。
3. **中文双副词工具习惯提取缺失（已修复）**：`src/astroagent/memory_extractor.py` 放宽工具习惯正则副词次数为 `{1,2}`，使「我平时主要使用…」等常见中文表达能够正确提取。
4. **前端 TypeScript 可选字段守卫（已修复）**：`frontend/src/stores/memory.ts` 为 `data.preferences` 补充默认值回退，通过 `vue-tsc --noEmit` 与 `vite build`。
5. **Ruff 静态检查与格式化（已修复）**：修复 `src/astroagent/api/memory.py` `B008`（`Depends` 改为 `Annotated` 类型别名）、移除 2 处未用导入及 1 处多余 `encode("utf-8")`、收折超长行并完成 237 文件格式化。
6. **测试契约与夹具同步（已修复）**：修正 `tests/test_memory_core.py`（`Source.name="Gaia"`、`permit.authorized`）、`tests/test_memory_postgres.py`（内部认证行、`skill_resolution` 参数签名、`confirm=True`）、`tests/test_v21_postgres.py`（`auto_match=True` 新契约），以及 `frontend/tests/browser/{current-changes,plot-acceptance}.spec.ts` 和 `frontend/tests/compute-browser/compute.spec.ts` 适配移除 `ComposerSkillPicker` 后的交互入口。

## 3. 留待云端 CI 与正式发布流水线验证项

- Linux 托管 Runner 上的 `pip-audit`、Linux 资源限制用例（`test_linux_resource_limits.py`）以及 `containers/release/docker-bake.hcl` 全量 8 个正式镜像在 `ghcr.io/lct808846/siderfolio-*` 下的构建与推送。
- GCP 生产机首次自动将 `origin` 从旧地址切换为 `https://github.com/lct808846/siderfolio.git`、平滑更新应用容器并执行生产 HTTPS 冒烟与新增 `/api/v1/memories/summary` 匿名拦截校验。
- 生产环境登录后的人工视觉体验复核及外部实网天文查询（`-m live`）。
