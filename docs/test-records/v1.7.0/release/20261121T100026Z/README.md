# AstroAgent v1.7.0 发布复验

以 `v1.6.0` 为基线，覆盖本版新增的计算任务和程序选择，以及项目、会话、文献、绘图、Gaia 和科研流程的相关变更。浏览器使用独立端口和合成数据，计算实测使用专用 PostgreSQL。外部 Gaia 查询沿用此前的网络豁免，本轮用合成结果和 ADQL 断言核对参数及上限。

| 检查 | 结果与证据 |
| --- | --- |
| 后端离线回归 | 306 项通过，4 项按测试条件跳过。核对手动会话标题保留、Gaia 500 行上限、新增条件与反向区间拒绝。 [复验](pytest-release-scope-final.txt) · [首次结果](pytest-release-scope.txt) |
| 代码与 API 契约 | Python Ruff 检查与格式、OpenAPI 快照和 TypeScript 生成类型通过。 [Ruff](ruff-release.txt) · [契约](openapi-generation.txt) |
| 前端检查 | TypeScript、ESLint、Vitest 47 项单元测试通过。 [前端检查](frontend-checks-final.txt) |
| 浏览器 | Chromium 全套首轮复验 37 项通过，公开 PDF、真实容器绘图两项按条件跳过。修复最后一项后，单独复验项目创建、快照、重跑、对比、ZIP 恢复与窄屏切换通过。 [整套](browser-release.txt) · [项目流程复验](browser-project-verified.txt) |
| 依赖 | npm 生产与完整依赖两次审计均为 0 项发现。 [生产](npm-audit-production-final.json) · [完整](npm-audit-all-final.json) |
| 计算实测 | REBOUND 与 PeTar 在独立容器中核对了双体、隔离、取消、超时与导出。12 体 Plummer 样例正常显示 PeTar 能量偏差告警。 [REBOUND](../../changed-parts/20261118T112200Z/README.md) · [PeTar](../../changed-parts/20261121T092707Z/README.md) |

浏览器首轮查出部分脚本仍引用旧入口。复验修复了项目绘图打开时异步选错空间、新建项目表单标识重复，以及窄屏项目面板切换栏被内容遮挡。原始失败和跳过记录保留。 [首轮](browser-initial.txt) · [复验](browser-release.txt)

Linux 前端首次构建未取得 Rollup 的平台包。按原锁文件重试后，正式后端、前端和计算镜像均完成构建。 [首次构建](container-build-final.txt) · [最终前端构建](container-build-frontend-release.txt)
