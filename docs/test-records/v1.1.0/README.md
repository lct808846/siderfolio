# V1.1.0 验收记录

2026-11-02 基于本地 `43aa495` 及 V1.1 工作区，使用隔离 PostgreSQL、合成数据和公开论文；未使用个人项目数据库或私人文献。版本元数据已同步为 1.1.0。

- [后端与 PostgreSQL 回归](offline-tests/20261102T034831091320Z/report.json)：536 通过、20 跳过，Ruff 和依赖检查通过。
- [前端检查](frontend-tests/20261102T035359895736Z/report.json)：类型、lint、15 项单元测试、构建及接口一致性通过；本机默认 Node 22 不符合要求，使用 Node 24.22.1 隔离副本。首次原目录 npm ci 因占用文件失败，记录保留；已恢复缺失的依赖文件。
- [浏览器回归](browser-tests/20261102T0410Z/playwright.json)：Chromium 和 Edge 共 26 通过、2 跳过；随后提供固定哈希公开论文完成 [2 项 PDF 引用与下载补测](browser-tests/20261102T0420Z/playwright.json)。九个宽度的面板切换、草稿保持与无自动发送、键盘及强制颜色/减少动态效果 [4 项通过](browser-tests/20261102T0440Z/playwright.json)。隔离副本采用 15173/18080 端口，避免占用现有服务。
- 初次浏览器运行 4 失败：改版后的标题测试未同步，且窄屏项目列表隐藏导入错误。更新标题断言并修复错误提示所在面板后重跑通过；失败记录保留在 [原报告](browser-tests/20261102T0400Z/playwright.json)。空项目时不再显示无效的项目导航。
- [真实 PostgreSQL + 浏览器](browser-postgres/20261102T0430Z/browser.json)：Chromium、Edge 预览和取消通过，未发送回答请求；[实际 TCP 测试](tcp-postgres/20261102T035518522682Z/report.json) 初始化、上传、检索及重启恢复通过。临时数据库和服务已清理。
- 真实服务： [Gaia 7 项](live-gaia-tests/20261102T034830951408Z/report.json)、[SIMBAD 2 项](live-tests/20261102T035205850665Z/report.json)、[ADS 6 项](live-ads-tests/20261102T035207161758Z/report.json) 均通过。Gaia 本轮已实测成功，旧版超时记录不改写。

浏览器截图使用合成数据；已检查桌面和窄屏代表画面。自动化检查不等同于完整屏幕阅读器、所有字体/操作系统或所有科学问题的验证；V1.0 文献检索小样本和科学忠实度的限制仍适用。最终提交的远程 CI 及发布状态以 GitHub 实际结果为准。
