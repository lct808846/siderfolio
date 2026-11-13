# 精确提交远程验收补充

首个提交 `158bb111b37df905c0763a9a851f1457f3e88d4b` 的[远程检查](https://github.com/lct808846/astroagent/actions/runs/43426907612)中，后端离线与前端检查通过；PostgreSQL组49通过、1失败。

失败为 `tests/test_plot_postgres.py::test_plot_lifecycle_confirmations_and_export` 返回503 `plot_sandbox_unavailable`。该用例实际执行隔离绘图并验证项目归档，不只是数据库测试。本机已有固定绘图镜像及启用配置，GitHub的全新Linux环境没有准备它们，执行被安全拒绝，没有回退宿主机。此前CI只跑部分数据库用例时未覆盖这一环境要求。

修复仅补全CI前置环境：在GitHub临时Runner构建仓库内已有的Python和Gnuplot绘图运行时，以构建后的SHA256固定身份，显式启用隔离执行后运行全部数据库用例。保留原测试断言与全部安全限制，不用模拟执行替换真实执行；不影响本机容器、科研数据库或模型。此后的结果以修复提交和对应标签CI为准。
