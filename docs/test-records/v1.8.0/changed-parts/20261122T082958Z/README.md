# AstroAgent V1.8.0 当前改动验收

2026-11-22。以 V1.7.0 的 `b1c0cc4a878ab72f8db91f19bda865d3d264e967` 为基线，验收本机 V1.8.0 工作区的 142 个改动文件。最终文件清单及内容指纹见 [tested-source.json](tested-source.json)。功能测试使用独立 PostgreSQL、隔离执行环境和合成科研数据。SIMBAD、ADS 和 Gaia 的联网查询另有实测记录。

## 结果

| 范围 | 结果与证据 |
| --- | --- |
| 后端离线回归 | 661 通过，5 按运行条件跳过，106 由 `live`、`postgres` 标记筛除。覆盖 MCP 发现、科学字段与直连一致性、并发限额、失败映射、超限响应、进程回收和历史快照导出。[离线日志](pytest-offline-verified.txt) |
| PostgreSQL 与实际绘图 | 独立 PostgreSQL/pgvector 验收 66 项通过，覆盖身份、项目、RAG、会话命名、计算任务及 MCP 设置持久化。另有 1 项使用真实隔离绘图执行器，验证 PNG、PDF、哈希和下载归档。[数据库日志](pytest-postgres-final.txt) · [绘图日志](pytest-plot-real.txt) |
| 前端与 API 契约 | Vitest 47 项通过。Ruff 检查和格式检查、ESLint、生产构建和 OpenAPI/TypeScript 同步校验通过。当次 `npm audit` 返回 0 项，后端 `pip check` 通过。[静态及单元检查](lint-unit-final.txt) · [最终 ESLint](eslint-confirmed.txt) · [API 契约](openapi-generated.txt) · [npm 审计](npm-audit-current.json) · [后端依赖检查](container-pip-check.txt) |
| Chromium 自动验收 | 工作台 41 项与邮件导航 6 项通过。验证对话内确认绘图与 N 体模拟、结果刷新恢复、MCP 设置、科研流程、项目快照及 ZIP 恢复。项目案例验证了 390 px 宽度下查看恢复的完整结果，以及删除项目后会话仍可访问。邮件导航用合成邮箱页面验证激活和重置链接。[工作台日志](browser-chromium-confirmed.txt) · [邮件导航日志](browser-mail-stable.txt) |
| MCP 真实数据 | AstroAgent 的 MCP 调用和独立 MCP Inspector 2.16.0 均协商到 `2026-07-28`，发现并调用 SIMBAD、ADS、Gaia 三项工具。AstroAgent 返回 M45 坐标、3 篇 ADS 文献和 1 条 Gaia 记录，Inspector 返回 1 篇 ADS 文献及同一 Gaia `source_id`。AstroAgent 的模型选工具步骤使用固定验收输入。[AstroAgent 查询](mcp-live-agent.json) · [Inspector 查询](inspector-live-summary.json) · [工具清单](inspector-modern-tools-list.txt) |
| N 体模拟 | 容器内 REBOUND 与 PeTar 均跑完双体样例，各交付 129 帧。该样例验证两种引擎可执行并交付结果，范围限于这组输入。[执行结果](compute-worker-live-smoke.json) |
| 容器与代理 | 前端、后端和入口代理镜像构建通过。独立环境中测试前端单独重建、显式重启、三项应用服务一起重建，操作后均能打开登录和激活入口并访问合成项目 API。仅重建前端时入口未重启，显式重启前端会联动重启入口。[后端构建](container-build-final.txt) · [前端构建](container-frontend-confirmed.txt) · [入口构建](container-ingress-recheck.txt) · [独立复验](isolated-ingress-restart.json) |

## 修复与复验

- 修复 MCP 并发限额未能跨请求正确共享，以及超限响应到达后客户端仍等待并误报超时的问题。
- 修复导出历史快照时新增可选字段影响旧档案校验的问题。原始字段缺省状态随备份保留。
- 修复项目导出刷新后面板跳到其他标签页、手机宽度下快照预览被隐藏的问题。复验覆盖同名项目恢复、完整预览和会话保留。
- 修复窄屏工作流切换时页面未就绪的问题，并恢复对系统降低透明度设置的响应。
- 早期运行的失败和重试日志已保留。初次使用 Node 24.15 运行邮件或项目测试时有本机进程异常，最终浏览器复验使用现有 Node 24.22.3。

## 按条件跳过的项目

- 后端 5 项包括 Windows Job Object 的两个用例、Windows TCP 监听检测、需指定公开 PDF 的用例和 256 MiB 磁盘用例。
- Chromium 有 2 项按配置跳过，分别是公开 PDF 原文下载和旧版独立绘图历史页。新版绘图卡片及真实执行器分别有通过证据。浏览器覆盖为 Chromium。

## 本机启动

已更新正在运行的前端、后端和入口代理到本次构建的镜像，三个应用容器及原有 PostgreSQL、Ollama、模拟工作进程和绘图执行器均通过启动健康检查。登录页返回 `200`，匿名会话请求返回 `401 login_required`。保留原有 PostgreSQL、模型及执行服务容器和数据卷。[启动检查](local-startup-health.json)
