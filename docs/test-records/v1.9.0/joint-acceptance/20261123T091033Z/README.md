# AstroAgent V1.9.0 联合验收记录

2026-11-23。以 V1.8.0 的 `d437730bf70272073e38b76a025b50c98533b322` 为基线，联合验收 V1.9.0 已发布源码提交 `746d3bea778e1dfef51269743549d8038f69ea0d`（74 个改动文件）及其在 V2.0.0（Siderfolio）工作区中的完整回归与修复验证。V1.9.0 源码范围与内容指纹见 [tested-source.json](tested-source.json)；联合验收完整自动化日志与多租户隔离实测见 [V2.0.0 联合验收目录](../../../v2.0.0/joint-acceptance/20261123T091033Z/README.md)。

## 结果

| 范围 | 结果与证据 |
| --- | --- |
| 固定科研评估框架 (`evaluate_v19.py`) | V1.9.0 原始提交运行 `scripts/evaluate_v19.py --mode offline` 时，因 `literature_schemas.py` 与 `schemas.py` 循环导入在导入阶段失败（已完整保留原始失败日志）。在工作区提取 `source_schemas.py` 并补齐 `al-05-ambiguous-reference-rejected` 离线构造字段后，离线确定性评估 6 项通过、0 项失败、4 项按 `live` 模式跳过。[原始失败日志](evaluate.txt) · [修复后评估报告](evaluation-report.json) · [修复后控制台输出](../../../v2.0.0/joint-acceptance/20261123T091033Z/evaluate-verified.txt) |
| 个人文献库与运行追踪端到端验证 | 在独立 PostgreSQL 容器中验证：对话内受 `SavePermit` 授权调用 `save_literature` 直接入库前 3 篇 ADS 文献并生成回执；手动入库与重复幂等重放（`replayed: true`）；已入库文献重复保存时完整保留用户自定义标签与私人备注；删除来源会话后文献条目仍可读且标记 `source_available: false`；运行追踪 `RunTrace` 准确记录 `model`、`tool_ads`、`tool_literature_save` 耗时与基于 `ASTROAGENT_MODEL_PRICING_JSON` 的费用估算，且严格排除提示词全文、论文摘要、私人备注与密钥；跨账号读写/删除文献或读取运行追踪均返回 `404`；独立 MCP 服务仅暴露 3 个只读工具（`query_gaia`、`query_simbad`、`search_ads`）。[隔离与功能实测 JSON](../../../v2.0.0/joint-acceptance/20261123T091033Z/v19-v20-isolation-quota-restore.json) |
| 后端离线与 PostgreSQL 回归 | 联合工作区下后端离线回归 661 项通过、5 项按运行条件跳过；独立 PostgreSQL/pgvector 与真实隔离绘图执行器 91 项全部通过（0 跳过）。[离线最终日志](../../../v2.0.0/joint-acceptance/20261123T091033Z/offline-final.txt) · [数据库最终日志](../../../v2.0.0/joint-acceptance/20261123T091033Z/postgres-final.txt) |
| 前端与 Chromium 浏览器回归 | Vitest 47 项单元测试通过；Chromium 工作台 41 项通过（2 项按条件跳过）、邮件导航 6 项通过，覆盖 V1.9 流式轮次 `/turns/stream`、会话包 `/bundle`、内联 N 体与绘图确认卡片及结果与文件面板。[前端状态](../../../v2.0.0/joint-acceptance/20261123T091033Z/frontend-status.json) · [工作台浏览器日志](../../../v2.0.0/joint-acceptance/20261123T091033Z/browser-chromium-confirmed.txt) |

## 发现与修复的问题

1. **`literature_schemas` 与 `schemas` 循环导入**：`scripts/evaluate_v19.py` 先导入 `astroagent.literature_auth`（触发 `literature_schemas` -> `schemas` -> `literature_schemas`），导致 `ImportError: cannot import name 'LiteratureSaveReceipt'`。已将共用 `Source` 模型提取至 `src/astroagent/source_schemas.py`，解除循环依赖。
2. **评估脚本离线样例 `al-05-ambiguous-reference-rejected` 构造缺失字段**：离线构造 `LiteratureSearchResult` 时缺少必填的 `rows`、`start`、`sort` 字段，且 `source_turn_id="t-1"` 在进入 `SavePermit.verify_and_resolve()` 前即被 Pydantic UUID 校验拦截。已补齐合法字段与 UUID，确保真实覆盖服务端多批次歧义拒绝逻辑。
3. **历史 V0.3 快照导出兼容**：`ChatResponse` 新增 `literature_receipts` 后，`ExportSnapshot` 在 `exclude_unset` 校验旧快照时报错；已在 `src/astroagent/export_schemas.py` 与 `src/astroagent/exports.py` 中将其设为可选默认空列表。
4. **会话历史窗口测试断言同步**：`tests/test_conversations.py` 中 `test_context_whole_turn_window_and_bytes` 仍断言旧版 6 轮上限，已同步至 V1.9 的 `MAX_HISTORY_TURNS = 24` 与 `256 KiB` 预算。
