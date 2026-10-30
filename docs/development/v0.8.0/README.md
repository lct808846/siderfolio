# V0.8.0 开发记录（非测试报告）

日期2026-10-30，源码基线 `9b16fe9`。开发阶段当时仅写入实现代码、界面及32条合成评估样本；后续执行结果见 [测试记录](../../test-records/v0.8.0/README.md)。

开始时已有README、路线图及未提交的V0.8开发契约。原始文件与工作区diff保存在 [baseline/20261030T004101633365Z](baseline/20261030T004101633365Z/baseline.json)，实施遵守其项目范围、原文定位、受限解析、引用、隐私及归档约定。

| 部分 | 源码 |
| --- | --- |
| 数据契约 | `knowledge_schemas.py`：文档、版本、位置、证据、上传/操作与摘录结果 |
| 存储 | `knowledge.py`：schema4、文件BLOB、索引、预算、幂等操作、中断与删除失效 |
| 提取 | `knowledge_parser.py` / `knowledge_worker.py`：独立进程、握手、Windows Job Object/Linux限制、超时终止 |
| 分段与检索 | `knowledge_text.py` / `knowledge_service.py`：原文位置、Unicode规范化副本、FTS5/短中文扫描、确定性排序与引用核对 |
| 归档 | `knowledge_archives.py`：格式3完整/仅元数据、关系检查、同哈希恢复与身份映射 |
| API与网页 | `api/knowledge.py`、Vue `KnowledgeWorkspace.vue`：上传、版本、检索、提取文本/原文件、证据、恢复和删除 |
| 评估资产 | `scripts/knowledge_eval/corpus.md`、`cases.json`、`evaluate_knowledge.py`：32条预先标注案例与显式执行入口；结果见测试记录 |

按用户要求，开发阶段不主动运行测试。本轮只进行了源码/文档读取编辑、原始改动备份、源码格式化、OpenAPI/TypeScript生成及评估样本编写。查阅官方依赖与SQLite文档用于实现，没有将查文档当作联网验收。

**没有执行**：新依赖安装、pytest、Ruff检查、类型检查、前端测试/构建、评估脚本、浏览器、应用启动、真实HTTP、联网验收、CI、提交/推送/标签/发布。接口代码生成不运行应用lifespan，不执行数据库迁移；个人 `.astroagent/astroagent.sqlite3` 未操作。既有测试源文件仅适配schema4预期，不表示已运行。

历史V0.7及更早测试证据保持原样，没有创建或改名复制成本版通过报告。[机器可读状态](development.json)中的执行列表均为空；后续安排见 [待验收清单](ACCEPTANCE.md)。

依赖依据：[pypdf 6.21.4](https://pypi.org/project/pypdf/6.21.4/)、[python-multipart](https://pypi.org/project/python-multipart/)、[SQLite FTS5](https://www.sqlite.org/fts5.html)。支持范围和限制见 [开发契约](../../PROJECT_PLAN_V0.8.md) 与 [开发版说明](../../releases/v0.8.0.md)。
