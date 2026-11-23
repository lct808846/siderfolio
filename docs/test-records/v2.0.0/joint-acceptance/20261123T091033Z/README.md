# Siderfolio V2.0.0（含 V1.9.0）联合测试验收记录

2026-11-23。以 V1.8.0（`d437730bf70272073e38b76a025b50c98533b322`）和 V1.9.0（`746d3bea778e1dfef51269743549d8038f69ea0d`）为基线，对 V1.9.0 与 V2.0.0（更名为 **Siderfolio**）进行联合测试验收，并在过程中修复发现的代码与测试问题。最终纳入 V2.0.0 验收范围的 115 个工作区改动文件及 SHA-256 指纹见 [tested-source.json](tested-source.json)，初始工作区状态见 [initial-scope.txt](initial-scope.txt)。所有数据库与破坏性演练均在独立临时 PostgreSQL 容器中执行，未向本机 `astroagent-v16` 日常数据库写入测试样本。

## 结果汇总

| 范围 | 结果与证据 |
| --- | --- |
| Python 静态检查与依赖校验 | 初次 Ruff 检查发现 17 处行宽/导入问题及 16 个待格式化文件（已保留初次失败记录）。修复后 `ruff check src tests scripts`（0 错误）、`ruff format --check src tests scripts`（207 个文件通过）、`compileall` 与容器内 `pip check` 全部通过。[初次 Ruff](ruff-first.txt) · [初次格式检查](ruff-format-first.txt) · [最终 Ruff](ruff-final.txt) · [最终格式检查](ruff-format-final.txt) · [编译与 pip check](python-compile-pip-check.txt) |
| V1.9 固定科研评估 (`evaluate_v19.py`) | 修复 V1.9 循环导入与 `al-05` 离线样例构造后，6 项离线确定性评估全部通过，4 项按 `live` 模式跳过。[V1.9 初次失败](../../../v1.9.0/joint-acceptance/20261123T091033Z/evaluate.txt) · [修复后评估输出](evaluate-verified.txt) · [结构化评估报告](../../../v1.9.0/joint-acceptance/20261123T091033Z/evaluation-report.json) |
| 后端离线回归 (`not live and not postgres`) | 初次运行 657 通过、4 失败、5 跳过。修复历史快照导出兼容、24 轮上下文窗口测试断言、品牌名 `Siderfolio` 断言与测试夹具 `namespace` 字段后，复验 **661 通过、0 失败、5 按运行条件跳过**。[初次离线日志](offline.txt) · [失败项单测复验](offline-failed-retest.txt) · [最终离线日志](offline-final.txt) · [最终离线 JUnit](offline-final.xml) |
| PostgreSQL 与真实隔离绘图 (`postgres and not live`) | 初次运行 89 通过、2 失败（TOTP issuer 品牌名断言、独立容器未挂载隔离绘图执行器）。修复 TOTP 断言并为测试容器接入真实 `astroagent-plot-executor:1.6.0` 侧车及绘图镜像后，复验 **91 通过、0 失败、0 跳过**，并通过 `scripts/ci_verify.py postgres` 覆盖率门槛校验。[初次数据库日志](postgres.txt) · [真实隔离绘图复验](postgres-plot-real.txt) · [最终数据库日志](postgres-final.txt) · [最终数据库 JUnit](postgres-final.xml) · [CI 门槛校验](ci-verify-postgres.txt) |
| REBOUND 与 PeTar 双体基准 (`ci_verify.py compute`) | 修复 `scripts/ci_verify.py` 中 `particles` 列表索引及只读根文件系统下 PeTar 工作目录后，在只读无网的 `astroagent-compute-worker:1.7.0` 容器内实测 1 yr 等质量圆轨道双体：REBOUND（容差 `1e-08`）与 PeTar（容差 `1e-05`）均通过。[计算校验输出](compute-worker-ci-verify.txt) |
| 多账号隔离、个人文献库、运行追踪、配额与备份恢复演练 | 在独立 PostgreSQL 实例中创建管理员、Alice、Bob 三个账号：验证 V1.9 对话内 Agent `SavePermit` 直接入库前 3 篇文献、手动入库与幂等重放、重入库保留原有标签与备注、删除会话后文献仍可读（`source_available: false`）、运行追踪脱敏与费用估算、跨账号访问返回 `404`；验证 V2.0 管理员修改单账号配额、审计记录、容量监控、Alice 天文查询额度耗尽返回 `429 astronomy_queries_quota` 且不影响 Bob；使用 `pg_dump --format=custom` 导出（218,838 字节，`PGDMP` 校验通过）并通过 `pg_restore` 恢复至第二个独立数据库，验证账号登录、5 篇文献、2 条入库回执、运行追踪与计算任务完整恢复（未完成运行态任务按可靠性契约恢复为 `interrupted`）。[演练完整证据 JSON](v19-v20-isolation-quota-restore.json) |
| OpenAPI 契约、前端单元、构建与依赖审计 | OpenAPI 快照与 `frontend/src/types/generated.ts` 同步校验通过；`vue-tsc --noEmit`、ESLint（`--max-warnings 0`）、Vitest（10 个文件 **47 项通过**）与 Vite 生产构建全部通过；生产与全量 `npm audit` 均为 **0 漏洞**。[OpenAPI 校验](openapi-contract-check.txt) · [前端检查汇总](frontend-status.json) · [Typecheck](frontend-typecheck.txt) · [ESLint](frontend-lint.txt) · [Vitest](frontend-test.txt) · [Vite 构建](frontend-build.txt) · [生产 npm 审计](npm-audit-prod.txt) · [全量 npm 审计](npm-audit-all.json) |
| Chromium 浏览器自动验收 | 邮件导航套件 **6 项全部通过**。工作台套件初次运行 32 通过、9 失败、2 跳过（因 V1.9/V2.0 界面文案、`/turns/stream` 流式路由、管理员表格新增「配额」按钮及结果面板标签调整）；更新 6 个浏览器测试文件后，全量复验 **41 项通过、0 失败、2 项按配置跳过**。[邮件导航日志](browser-mail-navigation.txt) · [初次工作台日志](browser-chromium.txt) · [9 项修复复验](browser-retest-9.txt) · [最终工作台全量日志](browser-chromium-confirmed.txt) · [最终工作台 JSON](browser-chromium-confirmed.json) |
| MCP 真实天文查询实测 | 在隔离容器内启用 `ASTROAGENT_ASTRONOMY_TOOL_TRANSPORT=mcp`，协商协议版本 `2026-07-28`（服务端版本 `2.0.0`，只读工具 `query_simbad`、`search_ads`、`query_gaia`）。SIMBAD 真实返回 M45 坐标 `[56.600833333333334, 24.11388888888889]`，ADS 真实返回 3 篇论文；Gaia 查询在当次联网时因上游 ESA ESDC Archives 处于计划维护停机（返回 HTML `<title>ESDC Archives downtime</title>`）被 `GaiaService` 安全拦截并归类为 `gaia_unexpected_response`，整体聊天响应按契约降级为 `partial` 并完整保留已成功的 SIMBAD 与 ADS 结果。[MCP 实测记录](mcp-live-agent.json) |

## 过程中发现并修复的问题

1. **V1.9 `literature_schemas` 与 `schemas` 循环导入**：提取 `Source` 至 `src/astroagent/source_schemas.py`，并在 `scripts/evaluate_v19.py` 中补齐 `al-05-ambiguous-reference-rejected` 离线构造所需的 `LiteratureSearchResult` 字段与合法 UUID。
2. **历史快照导出向前兼容（`src/astroagent/export_schemas.py`、`src/astroagent/exports.py`）**：将 `ExportSnapshot.literature_receipts` 显式设为可选默认空列表，保证 V0.3 等旧版无该字段的快照仍可正常校验与导出。
3. **容器外/独立测试容器隔离绘图客户端启用条件（`src/astroagent/plot_service.py`）**：支持在配置了 64 位十六进制 `ASTROAGENT_PLOT_EXECUTOR_TOKEN` 时启用 `ExecutorClient`，使独立 PostgreSQL 验收容器能够连接隔离 `plot-executor` 侧车完成真实 Matplotlib/Gnuplot 容器绘图。
4. **双体科学基准校验脚本（`scripts/ci_verify.py`）**：修正 `sample["particles"]` 的列表下标访问（`[0]`、`[1]`），并在运行 PeTar 前切换到可写临时目录 `os.chdir(root)`，解决 `--read-only` 容器根文件系统下 `/app/initial.dat` 写入报错。
5. **更名与 V1.9/V2.0 契约对应的测试更新**：
   - 后端测试：更新 `tests/test_conversations.py`（24 轮 / 256 KiB 历史窗口）、`tests/test_health.py` 与 `tests/test_identity_postgres.py`（`Siderfolio` 品牌标题与 TOTP issuer）、`tests/test_identity_security.py`（合成 `principal` 补齐 `namespace`）。
   - 前端单元与浏览器测试：更新 `frontend/tests/unit/qrcode.test.ts`、`frontend/tests/unit/workbench.test.ts` 及 6 个 Playwright 浏览器测试文件，对齐 `/turns/stream` 流式接口、`/bundle` 会话包、「结果与文件」面板、管理员「配额」按钮与内联确认卡片文案。
   - 重新生成并校验 `frontend/openapi.json` 与 `frontend/src/types/generated.ts`。

## 按条件跳过与未在本次本机环境验证的事项

- **按条件跳过的自动化用例**：
  - 后端离线测试跳过 5 项：Windows Job Object 进程树限制（2 项，容器内为 Linux）、Windows TCP 监听检测（1 项）、需外部指定公开 PDF 路径的用例（1 项）及 256 MiB 大磁盘写入用例（1 项）。
  - Chromium 浏览器测试跳过 2 项：`container-live.spec.ts`（旧版独立绘图历史页，现已由 `plot-acceptance.spec.ts` 与 PostgreSQL 真实隔离绘图用例覆盖）和 `knowledge.spec.ts` 中的外部公开 PDF 原文下载。
- **外部/生产环境待另行验证事项**：
  - **ESA Gaia TAP 实时上游**：本次验收期间 ESA ESDC Archives 官方服务器处于维护停机窗口（返回 HTML 维护页），Gaia 协议解析已在离线与 MCP 契约测试中完整验证，同时实测验证了上游维护时的安全拦截与 `partial` 降级保留能力。
  - **GCP 生产虚拟机公网部署与真实外部 SMTP 投递**：需在目标 GCP Linux 实例配置公网域名/IP、HTTPS 证书及真实 SMTP 凭据后，按《开发与发布手册》另行执行公网启动与收信验收。

## 本机容器更新与启动健康

代码与测试修复完成后，已执行 `.\scripts\containers.ps1 -Action update -Service frontend,backend` 构建并滚动更新本机 `astroagent-v16` 的 `frontend` 与 `backend` 服务，保留原有 `postgres`（`astroagent-v16_postgres_data` 数据卷）、`ollama`、`compute-worker` 与 `plot-executor` 容器及全部科研数据。7 个容器均处于 `healthy` 状态，`http://127.0.0.1:5173/login` 返回 `200`，匿名访问 `/api/v1/auth/session` 返回 `401 login_required`。所有带 `astroagent.acceptance=20261123T091033Z` 标签的临时测试容器均已清理完毕。[本机启动健康证据](local-startup-health.json)
