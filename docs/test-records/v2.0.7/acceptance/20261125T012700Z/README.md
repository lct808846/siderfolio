# Siderfolio v2.0.7 本地测试与验收记录

- **目标版本**：`v2.0.7`（基于 `v2.0.6` / `e3e80c6328c27388ecc432ac726b57f1f2ebaa3d`）
- **验收时间（UTC）**：`2026-11-25T01:27:00Z`
- **变更范围**：
  1. **移动端性能优化（不减少视觉特效）**：静态星空 SVG 与错峰闪烁图层合成、轨道光斑独立紧凑 GPU 合成层、移除移动端高频全屏重绘，涉及 `AstroBackdrop.vue`、`workspace-theme.css`、`conversation-layout.css`、`InteractionHints.vue`、`ConversationSidebar.vue`、`SettingsSelect.vue`、`App.vue`。
  2. **错误提示统一与移除独立「刷新」按钮**：统一操作与读取错误为 `StatusNotice` 顶层浮层（`popover="manual"`），移除各页面/弹窗独立刷新按钮，同步更新 `AGENTS.md` 与 `docs/UI_DESIGN_SPEC.md`。
  3. **多设备登录详情与异常登录检测**：新增 `src/astroagent/auth_device.py`、兼容扩展 `public.auth_sessions` 12 列元数据（`ADD COLUMN IF NOT EXISTS`）、信任 Cloudflare/Ingress 边缘地理位置头并剥离客户端伪造头、异常登录发送中文安全提醒邮件且不强制下线、前端账号安全面板展示多设备详情并支持单台/一键强制退出其他设备。

## 本地验收汇总

| 检查项 | 命令 / 环境 | 结果 | 说明 |
| --- | --- | --- | --- |
| OpenAPI 与前端类型契约 | `python scripts/generate_frontend_types.py --check` | 通过 | OpenAPI 快照与 `frontend/src/types/generated.ts` 一致 |
| Python 编译与静态检查 | `compileall`、`ruff check src tests scripts`、`ruff format --check src tests scripts`、`pip check` | 通过 | 212 个文件格式一致，零 lint 警告，依赖无冲突 |
| Python 离线单测 | `pytest -m "not live and not postgres" -ra` | 672 passed, 4 skipped, 0 failed | 跳过项：`test_knowledge.py:261`（需显式公开 PDF 夹具）、`test_knowledge.py:524`（需显式开启 256 MiB 磁盘验收）、`test_linux_resource_limits.py:44,73`（仅 Linux） |
| 隔离 PostgreSQL + 真实绘图 | 临时 `pgvector/pgvector:0.8.7-pg16-bookworm`（`127.0.0.1:55432`）+ `astroagent-dev-plot-python:local` + `astroagent-dev-plot-gnuplot:local`；`pytest -m "postgres and not live" -ra` + `scripts/ci_verify.py postgres` | 96 passed, 0 skipped, 0 failed | 覆盖身份隔离、多设备登录详情与异常提醒邮件、反馈权限、真实容器绘图、计算队列、RAG 边界；未接触日常库 `astroagent_dev` |
| 数值计算沙箱验收 | `scripts/ci_verify.py compute`（`--network none --read-only --cap-drop ALL`） | 通过 | REBOUND（误差 `< 1e-8`）与 PeTar（误差 `< 1e-5`）圆轨道双星校验通过 |
| 前端静态检查、单测与安全审计 | `npm run typecheck`、`npm run lint`、`npm test`、`npm audit --omit=dev --audit-level=high`、`scripts/check_frontend_audit.py`、`npm run build` | 通过 | Vitest 10 文件 / 47 用例全通；零高危漏洞；生产构建成功（保留既有主包 >500 kB Vite 提示） |
| Node 入口脚本语法与生产 Caddyfile | `node --check containers/frontend/ingress.mjs`、`node --check frontend/server.mjs`、固定生产 Caddy 镜像 `caddy validate` | 通过 | 边缘地理位置头清理与转发逻辑、生产 Caddyfile 校验通过（`Valid configuration`） |
| Playwright 邮件导航套件 | `npx playwright test --config playwright.mail-navigation.ts`（Chromium + Edge） | 12 passed, 0 failed | 跨站点击、激活确认、重置链接、两步登录流全通 |
| Playwright 浏览器套件 | `npm run test:browser` + `account-changes.spec.ts` 复跑（Chromium + Edge） | 86 passed, 4 skipped, 0 failed | 跳过项：`container-live.spec.ts`（×2 浏览器）与 `knowledge.spec.ts:50`（×2 浏览器），均为需显式环境夹具的条件用例 |
| 本机开发容器更新 | `.\scripts\dev.ps1 -Action Update` | 通过 | `astroagent-dev` 全部 6 个容器（`backend`、`frontend`、`postgres`、`compute-worker`、`ollama`、`plot-executor`）升级至 `2.0.7` 并健康运行于 `http://127.0.0.1:5173` |

## 首轮检查发现与修复记录

1. `src/astroagent/auth_device.py`：Python 3.12 `ipaddress.IPv4Address.is_private` 将 RFC 5737 测试网段（`198.51.100.0/24`、`203.0.113.0/24`）及 CGNAT 视作非全局地址，导致 `test_device_parsing_and_anomaly_detection` 误判为「本地 / 局域网」；已改为显式匹配回环、链路本地、未指定及 RFC 1918 / RFC 4193 局域网段，并修复 3 处 Ruff 行宽与格式。
2. `src/astroagent/auth_store.py`：修复 8 处 Ruff E501 行宽及 1 处格式换行。
3. `frontend/src/views/AdminWorkspace.vue`：修复第 434 行未定义模板引用 `actionDialog?.open` -> `dialog?.open`。
4. `frontend/server.mjs`：将 `cleanEdgeMeta` 控制字符正则改为 `/\p{Cc}/gu`，通过 ESLint `no-control-regex` 校验。
5. `frontend/src/components/StatusNotice.vue`：抽离模块级 `allocateToastId()`，消除 ESLint `no-useless-assignment` 误报。
6. `frontend/tests/browser/account-changes.spec.ts`：首轮 Playwright 暴露旧版「2 个会话 / 当前会话 / 退出此浏览器会话 / 退出此会话」选择器与新版多设备 UI 文案不一致；已更新测试夹具与断言覆盖多设备名称、异地登录标签及单设备强退密码确认流程，Chromium 与 Edge 复跑 8/8 通过。

## 未在本地执行的检查（由云端 CI / 正式发布流水线覆盖）

- Linux 容器生产镜像全量 Buildx 校验（`backend`、`frontend`、`ingress`、`postgres`、`compute-worker`、`plot-executor`）及 `pip-audit` 将在 `origin/main` 推送后的 GitHub Actions `Tests` 流水线与 `v2.0.7` `Formal release` 流水线执行。
- 生产环境部署、容器摘要核对与公网 HTTPS 冒烟检查将在 `v2.0.7` 标签触发发布完成后核验。
