# AstroAgent v1.8.0

V1.8.0 新增本地 Astronomy MCP Server，并将绘图和 N 体模拟接入对话。

- **天文查询**支持通过本地 `stdio` MCP 服务调用 SIMBAD、NASA ADS 和 Gaia DR3。默认使用直连，管理员可在网页中切换到 MCP。独立 MCP 客户端也可调用这三项只读工具。 [MCP 操作说明](OPERATIONS.md)
- **对话内绘图和模拟**支持审阅方案、确认执行和查看结果。N 体计算可选 REBOUND 或 PeTar，刷新会话后可重新查看结果。
- **科研项目**可在管理面板关联会话、复核快照，或导出和恢复 ZIP 备份。导入会创建独立项目，快照预览适配手机宽度。
- **工作台与设置**调整了账号、个人资料、外观和会话命名入口，并改进附件预览和提交反馈。

增量验收实测了三项天文数据源、隔离绘图和两种 N 体引擎的双体样例。验收样例及按条件跳过的用例见[增量验收记录](../../test-records/v1.8.0/changed-parts/20261122T082958Z/README.md)。

Docker 部署可沿用现有 PostgreSQL、模型和私有配置。本版通过 GitHub Release 提供源码压缩包。 [部署说明](OPERATIONS.md#3-linux-容器部署与切换)
