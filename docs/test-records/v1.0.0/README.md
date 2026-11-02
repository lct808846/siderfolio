# V1.0.0 验收记录（进行中）

本轮针对未提交工作区，基线为 `4abe8cd`，不代表最终提交或远程 CI。未使用个人数据库和私人文献。

- 离线和专用 PostgreSQL 回归：Windows 497 通过、19 跳过，Ruff、格式和依赖检查通过，见 [报告](offline-tests/20261101T135237336195Z/report.json)。初次离线测试本身通过，但静态检查有 36 项问题；修复后重跑通过，原报告保留。
- 原生 Windows PostgreSQL 16.15 的随机临时库：RAG 合成集成及 schema5 迁移、防重复导入共 [4 项通过](postgres-tests/20261101T1342Z/windows-native.xml)；真实 TCP 初始化、上传、词法预览和重启恢复 [8 项通过](tcp-postgres/20261101T134804439072Z/report.json)。WSL PostgreSQL 18.6 / pgvector 的对应集成和迁移 [4 项通过](postgres-tests/20261101T1342Z/linux.xml)。首次迁移测试误把带 WAL 的 SQLite 主文件当一致性备份导致失败；改用 SQLite backup API 后通过，失败证据保留。
- 整库备份、SHA、独立新库恢复、记录保留、拒绝覆盖分别在 [Windows](postgres-tests/20261101T1342Z/windows-dump-restore-retry.json) 与 [WSL](postgres-tests/20261101T1342Z/dump-restore.json) 通过。Windows 首次恢复检查因测试脚本误拼连接字符串失败，重试报告和初始失败均保留。
- 前端类型、lint、15 项单元测试、构建及 OpenAPI 类型比对 [通过](frontend-tests/20261101T133924054288Z/report.json)。旧 SQLite 替身浏览器回归 24 通过、2 项公开 PDF 跳过；新设置与 RAG 页面使用真实 Windows PostgreSQL 的 Chromium/Edge 桌面与窄屏 [通过](browser-postgres/20261101T1401Z/browser.json)，核对了预览及取消不发送。截图已查看，但未覆盖全部键盘、屏幕阅读及故障状态。
- 固定版本多语言 CPU 模型的两条合成中英文输入产生 384 维单位向量，见 [报告](model-tests/20261101T1350Z/report.json)。真实 TCP + PostgreSQL + 本地模型的索引、语义预览及一次真实回答服务调用见 [报告](tcp-postgres/20261101T135327998068Z/report.json)；实际返回 `insufficient_evidence`，不证明成功生成有引用的正文或真实文献质量。
- SIMBAD / 模型 2 项、ADS 6 项通过；Gaia 真实查询与依赖链路 7 项 [失败](live-gaia-tests/20261101T134038232131Z/report.json)，查询超时。旧版本的发布例外不等于本版通过。

本轮临时数据库、测试服务和 D 盘模型测试目录已清理，8000、5173、55439 端口无监听。测试时额外安装的 WSL PostgreSQL 18 保留在 WSL 中，其默认集群已停止且禁用自动启动；原有 Windows PostgreSQL 16 服务仍运行，管理员维护库连接核对版本为 16.15。105 个测试记录文件的本机凭据扫描未发现匹配。

上述为此前阶段的状态；下方记录后续自动化补测及用户明确的验收范围调整。

## 自动化补充验收

用户明确允许本次 Gaia 网络失败作为例外，并要求剩余验收不采用人工完成。Gaia 既有超时记录保留，例外不代表查询成功。自动检查不能证明文献结论的科学真实性或替代代表性语料验证。

- 最新 Windows 全量回归：516 通过、20 跳过，Ruff、格式和依赖检查通过，[报告](offline-tests/20261101T141922734524Z/report.json)。此次工作区尚未提交，不能替代最终提交的远程 CI。
- 真实 PostgreSQL 的 RAG 边界、256 MiB 逻辑数据、恢复、删除历史、锁和取消等自动化检查见 [17 项](rag-boundaries/20261101T1640Z/pytest.xml)、[恢复及历史](rag-boundaries/20261101T1650Z/pytest.xml)、[并发及 schema](rag-boundaries/20261101T1710Z/pytest.xml)、[取消](rag-boundaries/20261101T1700Z/pytest.xml)。256 MiB 测试使用可压缩合成数据，不代表物理容量或性能验收。旧 SQLite 替身的 PDF 与容量检查单独记录在 [报告](legacy-pdf-storage/20261101T1622Z/pytest.xml)。
- 发现并修复预览取消请求因缺少 JSON 类型而返回 415；真实 PostgreSQL 浏览器自动化检查实际取消响应和未发送回答，见 [报告](browser-postgres/20261101T1705Z/browser.json)。前端类型、lint、测试、构建和接口类型检查见 [报告](frontend-tests/20261101T141127000573Z/report.json)。
- 两篇公开论文首页、真实多语言嵌入模型和预先固定的机器定义样例构成探索性自动评估：[报告](automatic-evaluation/20261101T142010223427Z/report.json)。英文及中文各 2 条正例的混合检索 Recall@5 均为 1.0，引用回查无无效项；2 条无答案问题均返回候选内容，预览阶段拒绝率为 0，低于事先设定的 1.0 门槛，因此**未通过**。该小样本和自动锚点不能证明代表性或科学忠实度。
- 对相同的 2 条无答案问题另行调用真实回答模型，最终回答均为证据不足，[报告](automatic-evaluation/20261101T141551569711Z/report.json)；这不消除预览阶段的失败。真实模型成功生成带引用回答的合成链路见 [报告](tcp-postgres/20261101T141359814359Z/report.json)，仅证明引用格式及链路，不证明引用支持科学结论。

剩余限制：无答案检索预览未达到固定门槛；自动化小样本不能建立科学忠实度和代表性；尚未验证最终提交对应的远程 CI。不能宣称全部验收通过。

## 2026-11-02 本地模型重跑

使用用户准备的 D 盘多语言模型重跑固定方案，模型文件重新计算的 SHA-256 与原方案一致；临时数据库均已删除。[结果](automatic-evaluation/20261102T002648898080Z/report.json)：英文及中文各 2 条正例的混合检索 Recall@5 均为 1.0，引用回查无无效项；2 条无答案问题仍均返回候选内容，预览拒绝率为 0，未达到事先设定的 1.0 门槛，整体未通过。各次预览约 38–39 秒，仅为本次运行实测，不构成系统性能基准。本次未调用回答模型；上次回答阶段 2/2 表示证据不足的结果仍独立记录。Gaia 网络测试按用户授权继续作为例外。

## 2026-11-02 检索改动后自动重测

固定公开论文及模型的 [自动评估](automatic-evaluation/20261102T005023753421Z/report.json) 通过：英文和中文各 2 条正例的 Recall@5 为 1.0，2 条无答案短词均无结果，拒绝率为 1.0，引用回查无无效项。规则针对缺少原文匹配的简短字面查询；该小样本不能证明其他无答案问法或科学忠实度。

[PostgreSQL 全量回归](offline-tests/20261102T005357409012Z/report.json) 的 pytest 为 536 通过、20 跳过，依赖检查通过；原报告整体失败，因为新增测试文件有一处 Ruff 行宽和格式问题。随后仅格式化该文件，并重新运行全仓 Ruff 检查及格式检查（均通过），又重跑该文件的 16 项测试（全部通过）。原失败报告保留；格式化后的工作区未重新执行整套回归。临时数据库已删除。Gaia 按用户授权跳过，最终提交及远程 CI 仍待验证。

## 远程验证首次运行

验证提交 `a74804d8d310916076bddebb5c41f747624ff8df` 的 [GitHub Actions](https://github.com/lct808846/astroagent/actions/runs/41370793407) 中，后端和 PostgreSQL 通过，前端类型、lint、单元测试和构建通过；接口快照检查失败，导致浏览器步骤未执行。经对照 FastAPI 0.141.1 / Pydantic 2.13.4 与 FastAPI 0.162.0 / Pydantic 2.14.2，接口 JSON 内容相同，但对象字段顺序不同。后续修正生成顺序并在两套依赖下分别完成接口与生成类型一致性检查；修正提交的远程结果需单独确认。

## 远程验证通过

验证提交 `a53c6e0e1086b780c518350e84fdf7a83cd441c5` 的 [推送 CI](https://github.com/lct808846/astroagent/actions/runs/41371340439) 和 [合并请求 CI](https://github.com/lct808846/astroagent/actions/runs/41371345451) 均通过后端、PostgreSQL 和前端任务。推送 CI 中后端 508 通过、48 跳过，PostgreSQL 4 通过；前端单元 15 通过，浏览器 12 通过、1 跳过。首次接口快照失败及修正历史保留在前一节。Gaia 网络查询按用户授权作为例外，未重记为通过。
