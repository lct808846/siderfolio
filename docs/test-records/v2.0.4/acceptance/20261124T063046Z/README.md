# Siderfolio v2.0.4 本机测试验收记录

- **UTC 时间**：`2026-11-24T06:30:46Z`（北京时间 `2026-11-24 14:30:46`）
- **版本范围**：基于 `origin/main`（`5fdaacfe08ba214bf60e94ac69620ea5775f3cd1`，`v2.0.3`），包含移动端页面重构（全高侧栏抽屉、设置二级列表/详情视图、个人资料模型卡片、底部弹窗菜单与品牌图标）、长期登录会话策略优化、本机 `astroagent-dev` 5173 开发配置及 `v2.0.4` 版本元数据同步。
- **运行环境**：Windows 11 + Docker Desktop WSL2 Linux 引擎；Python `3.12.13`（`pytest 9.1.1`、`ruff 0.17.2`）；Node `v22.15.0`（生产容器与 GitHub Actions CI 使用 Node `24.22.1`）。

## 1. 检查汇总

| 检查项 | 最终结果 | 详情与跳过/修复记录 |
| --- | --- | --- |
| OpenAPI / TypeScript 契约 | 通过 | `scripts/generate_frontend_types.py --check` 通过，`frontend/openapi.json` 版本为 `2.0.4` |
| Python 编译与静态检查 | 通过 | `compileall` 0 错误；`ruff check src tests scripts` 全部通过；`ruff format --check` 207 个文件均合规；`pip check` 无冲突 |
| Python 离线单元测试 | 通过（修复 1 处） | 首轮运行 `pytest -m "not live and not postgres"` 为 665 passed, 1 failed, 4 skipped, 105 deselected（跳过项：`test_knowledge.py:261` 需显式本地 PDF、`test_knowledge.py:524` 需显式 256 MiB 磁盘验收、`test_linux_resource_limits.py:44,73` 为 Linux 专用限制）。修复 `src/astroagent/auth_access.py` 第 179 行 `authenticate(session, False)` 位置参数后，`tests/test_identity_security.py` 复测 17/17 通过 |
| 隔离 PostgreSQL 与真实绘图 | 通过 | 独立临时容器 `pgvector/pgvector@sha256:0dd3149a06e4579a0d70d8fef9945636cd514005e7237deb27f9b67886f8dc4f`（空库 `astroagent_test_control`，隔离于 `astroagent_dev`），挂载 `astroagent-dev-plot-python:local` 与 `astroagent-dev-plot-gnuplot:local`：`pytest -m "postgres and not live"` **90 passed, 0 failed, 0 skipped**；`scripts/ci_verify.py postgres` 通过 |
| 科学计算数值回归（REBOUND / PeTar） | 通过 | 使用 `astroagent-dev-compute:ea079ea85c6d5943e1cc` 在无网络只读受限容器内运行 `scripts/ci_verify.py compute`（两颗各 `0.5 M_sun`、间距 `1 AU`、周期 `1 yr` 孤立圆轨道双体，单位 `AU / M_sun / yr`）：REBOUND 通过（误差阈值 `1e-8`），PeTar 通过（误差阈值 `1e-5`，相对能量误差 `4.36e-14`） |
| 前端类型、Lint、单测、审计与构建 | 通过 | `vue-tsc --noEmit` 通过；`eslint . --max-warnings 0` 通过；Vitest `10/10` 文件 `47/47` 通过；`npm audit --omit=dev --audit-level=high` 0 漏洞；`scripts/check_frontend_audit.py` 全量依赖审计通过；`vite build` 产物 `dist/index.html` 正确重写 `/assets/siderfolio-logo-*.svg` |
| 邮件导航浏览器验收 | 通过 | `npx playwright test --config playwright.mail-navigation.ts`：**12 passed**（Chromium 6 + Edge 6） |
| 全量浏览器验收（Playwright） | 通过（修复 4 组窄屏项） | 首轮 `npm run test:browser`（Chromium + Edge 共 86 项）：74 passed, 4 skipped（`container-live.spec.ts` 与 `knowledge.spec.ts:50` 按条件跳过）, 8 failed（4 个窄屏用例在双浏览器一致失败）。修复以下两处真实移动端问题并适配三处新版移动端抽屉/结果层测试断言后，4 个目标测试文件复测 **48 passed, 0 failed**（Chromium 24 + Edge 24） |
| 手机端视口专项巡检 | 通过 | Playwright Chromium 在 `390×844` 与 `375×812` 下逐页检查 `/`、`/literature`、`/settings`、`/profile`：`scrollWidth == innerWidth`（零横向溢出）、`/favicon.ico` 返回 `200`、零静态资源 404、零 `pageerror`；侧栏抽屉打开/关闭及设置页 `list -> detail -> list` 切换正常 |

## 2. 本轮发现并修复的问题

1. **后端下载分块吊销鉴权兼容性**（`src/astroagent/auth_access.py`）：恢复 `identity.store.authenticate(session, False)` 位置参数调用，修复流式下载分块吊销测试失败。
2. **移动端设置页切窄视口丢失进行中表单**（`frontend/src/views/SettingsWorkspace.vue`）：在 `.settings-detail-reading` 捕获交互与聚焦事件同步设置 `mobileDetailOpen = true`，避免桌面端展开 MFA 二维码绑定后缩窄视口导致表单隐藏。
3. **移动端全高抽屉与结果层无障碍隔离**（`frontend/src/views/App.vue`）：当 `mobileOverlayOpen` 为真时为底层 `<main class="chat-panel">` 设置 `inert` 与 `aria-hidden="true"`，并在打开/关闭移动抽屉和结果层时规范接管焦点，消除被遮挡“新建会话”按钮与焦点泄漏。
4. **窄屏浏览器测试适配新版移动端交互**（`frontend/tests/browser/{profile-changes,remaining-acceptance,workbench}.spec.ts`）：在 `≤ 980px` 视口下改用抽屉内「关闭会话列表」按钮关闭侧栏，并按手机端不再强制自动弹出结果层的新交互顺序核对结果面板开关。

## 3. 留待 GitHub Actions CI 与发布流水线完成的验证

- `pip-audit` Python 依赖审计（本机虚拟环境未预装 `pip-audit`，由 GitHub Actions `Tests / test` 在 Linux Python 3.12 环境执行）。
- `containers/release/docker-bake.hcl` 全量 8 个正式 OCI 镜像构建与 GHCR 摘要发布，以及 `Formal release` 生产部署与 Release 附件归档。
