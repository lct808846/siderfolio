# V0.9.0 验收记录（未完成）

本轮针对未提交工作区，基线提交为 `4d92db2275a3ef05f3507f29b9812c7a08cda41c`；不能替代最终提交的 CI。未发布 V0.9.0。

- Windows 离线：491 通过、19 跳过，Ruff、格式、依赖检查通过，见 [报告](offline-tests/20261031T021207182778Z/report.json)。Linux WSL：490 通过、20 跳过，检查通过，见 [报告](offline-tests/20261031T021211647028Z/report.json)。超时测试运行期间的 30 秒线程堆栈为诊断输出，测试最终通过。
- 合成集成：18 项通过，见 [报告](integration/20261031T021217540461Z/report.json)。最初入口导入和 204 状态断言失败已修正，失败记录保留。知识检索的 32 条合成样本达到预设指标，见 [报告](knowledge-evaluation/20261031T020909381362Z/report.json)；不代表真实文献效果。
- 前端类型、lint、15 项单元测试、构建和类型契约通过，见 [报告](frontend-tests/20261031T021630843454Z/report.json)。既有浏览器回归 22 通过、2 个公开 PDF 场景跳过，见 [报告](browser-tests/20261031T021034944764Z/report.json)。新增关联页面 Chromium/Edge 各 1 项通过，见 [报告](overview-browser-20261031-r2/playwright.json)；覆盖创建、取消、原文、窄屏解除。先前失败暴露解除成功提示在窄屏隐藏，现已修复，失败报告保留。
- 独立包验证与既有流程 HTTP 回归通过，见 [包检查](release-audit/20261031T021108773873Z/report.json) 和 [HTTP](acceptance-v07/20261031T021110675152Z/report.json)。使用临时合成库实际验证 schema 5 整库备份、清单哈希、恢复后读取项目、拒绝覆盖已有目录；不是个人数据库演练。
- 真实 SIMBAD 2 项、ADS 6 项通过。真实 Gaia 7 项失败，返回 `gaia_timeout`；单条精确源复试仍超时。现有证据不足以判断是本机链路还是远端服务问题，见 [报告](live-gaia-tests/20261031T021127817986Z/report.json)。

当时仍需：恢复 Gaia 服务后重新验收；补齐公开文献评估和公开 PDF 浏览器检查；对新增关联页面及所有目标类型、断线/键盘/长文本和失效恢复作更完整的浏览器人工核查；独立 Windows/Linux 安装、备份恢复与格式4、限额/故障专项等按 [验收清单](../../development/v0.9.0/ACCEPTANCE.md) 逐项留证。后续结果见下方补充。该工作区有未提交的代码和测试记录。

## 后续补充（2026-10-31）

- 公开 PDF 和实际 256 MiB 存储边界，Windows、Ubuntu 各两项通过：[Windows](pdf-storage-tests/20261031T0224Z/pytest.xml)、[Linux](linux-pdf-storage-tests/20261031T0224Z/pytest.xml)。文件为 arXiv:1601.01752，SHA-256 `1d6061aa93ebf27b55dba44c41311d7dfad95f4f8f73161c1802b51f5cb714a2`。双浏览器包括公开 PDF 和关联页面共 [26 项通过](browser-tests/20261031T022003122565Z/report.json)。
- schema4→5 的备份、注入失败回滚、重试升级与原记录保留在 [Windows](schema5-tests/20261031T0225Z/windows.xml) 和 [Linux](schema5-tests/20261031T0225Z/linux.xml) 均通过。
- [单篇公开论文试评](real-literature-pilot/report.json)的四条定位和两条无答案均符合预设；这是小样本、同一提取器辅助定位，不是独立且有代表性的真实文库评估。题目文件中 UTC 时间误写为 02:24；实际文件写入时间为 02:21:13，评估报告写入时间为 02:21:42。保留原文件及其哈希，不伪造事前时间。

## 继续验收（2026-11-01）

- 全新 Windows Python 3.12 隔离环境执行完整离线检查：493 通过、19 跳过，Ruff、格式与依赖检查通过，见 [报告](offline-tests/20261101T024249540153Z/report.json)。Windows 新环境中的健康、schema5 和备份恢复另有 [JUnit](schema5-tests/20261031T0225Z/windows-fresh.xml)。
- [30 项合成集成场景](integration/20261101T024507102800Z/report.json)通过，补充了格式1–3导入及有历史时拒绝导出、关联请求冲突和旧修订冲突、格式4错误目标、重复关系、重复操作、未知成员的事务拒绝。属于进程内合成测试，不代表已穷举坏包和上限。
- 已查看 Chromium 关联总览和 Edge 窄屏原文截图；截图只证明所展示的状态，不代替所有目标类型和键盘/断线场景的逐项人工验收。
- 全新 Ubuntu 26.04 / Python 3.14 环境，独立安装及 FTS5、JSON 检查通过；使用 Node 24.15.0 在独立临时目录构建前端成功。完整离线检查 [492 通过、20 跳过](offline-tests/20261101T024259913063Z/report.json)，Ruff、格式和依赖检查通过。两平台备份、恢复和覆盖拒绝另见 [Windows](schema5-tests/20261031T0225Z/windows-backup.xml) 与 [Linux](schema5-tests/20261031T0225Z/linux-backup.xml)。
- [两篇公开论文小样本试评](real-literature-two-paper/report.json)的 6 条页面定位与 2 条无答案均达到执行前固定的门槛，引用回查未发现失效。仅涉及两篇英文论文，部分锚点借助同一 PDF 提取器选取，不能代表真实文库，也不是独立人工真值。
- Gaia 于 11 月 1 日 [完整复测](live-gaia-tests/20261101T024234299701Z/report.json)仍为 7 项失败，返回查询超时；Windows 与 WSL 直接访问查询端点也超时。能力接口此前返回 HTTP 200，不能证明实际查询可用，也不足以确定网络链路或远端服务为根因。
- 验收临时前后端已停止，Windows TCP 监听表的 8000、5173 端口为空；本次独立环境、临时 Linux 前端与下载的两份 PDF 已清理。

尚未完全验收：Gaia 真实查询；真实文献评估的独立标注和更具代表性的语料；关联页面其他目标类型、异常和辅助功能的人工覆盖；数量上限、恶意归档及其他边界的全部组合。用户于 2026-11-01 明确决定本次跳过 Gaia 联网验收并发布，后续版本再试；该例外不将失败改记为通过。最终提交及其 CI 以远端记录为准。
