# V0.7.0 开发记录（非测试报告）

状态：**实现代码已写入；未测试、未构建、未发布**。开发开始2026-10-29，收尾2026-10-30；基线 `2bda44a`。用户约定开发阶段不主动测试，发布前由用户安排验收。

## 实现范围

| 部分 | 代码位置与行为 |
| --- | --- |
| 模板与参数 | `workflow_schemas.py` / `workflow_templates.py`：固定Gaia视场与ADS证据表，精确参数、步骤、版本及依赖摘要 |
| 持久记录 | `workflows.py`：创建、执行预留、尝试、检查点、快照引用、文件、删除和启动中断恢复 |
| 执行与科学输出 | `workflow_service.py`：复用现有科研服务和V0.4导出器，不构造模型；保存完整响应与原始摘要 |
| 归档与文件边界 | `workflow_archives.py` / `workflow_io.py`：格式2、身份映射、完整性与关系验证、固定ZIP成员、CSV保护 |
| 旧模块适配 | schema3迁移、统一字节预算、项目忙锁与快照引用保护；旧项目归档格式1仍可显式使用 |
| API | `api/workflows.py`：模板、运行列表/详情/创建/确认执行/文件/删除；错误继续使用原安全契约 |
| Vue | `WorkflowWorkspace.vue`、流程API与路由、项目入口、确认弹窗、逐次尝试、刷新/幂等核对、持久下载与窄屏面板 |
| 文档与元数据 | Python/前端版本0.7.0、生成的OpenAPI/TypeScript、README/路线图/开发说明及待验收清单 |

本地科学查询、统计和V0.4导出模块继续复用。输入不可就地修改，改参数需新建运行；导入历史只读。执行状态与查询 `success/not_found/error`、导出 `success/partial` 分开显示。

## 已执行的开发操作

只进行了源码/文档读取编辑、保存用户原始改动、源码格式化，以及不带 `--check` 的OpenAPI/TypeScript代码生成。代码生成未运行应用lifespan、未启动服务、未访问科研服务或执行数据库迁移。

没有执行pytest、Ruff检查、依赖检查、TypeScript检查、前端测试、生产构建、浏览器/截图、真实HTTP/联网验收、软件包验收或CI；没有提交、推送、打标签或发布。`tests/test_projects.py`和旧 `verify_v06.py`仅在源码层适配最终schema3与显式格式1，不代表这些旧检查已在V0.7上运行。

历史 `docs/test-records/v0.6.0` 保持原样。这里没有通过/失败统计，不创建伪造的V0.7测试报告。

## 原始工作区保留

开始时已有README、路线图及未提交的V0.7开发文档。原文档与当时diff保存在 [baseline/20261029T145405532374Z](baseline/20261029T145405532374Z/baseline.json)；实现基于这些已有约定，未将其覆盖成旧版本内容。未操作 `.astroagent/astroagent.sqlite3`，未运行迁移或归档个人数据。

相关资料：[开发契约](../../PROJECT_PLAN_V0.7.md)、[开发版说明](../../releases/v0.7.0.md)、[发布前待验收清单](ACCEPTANCE.md)、[机器可读状态](development.json)。
