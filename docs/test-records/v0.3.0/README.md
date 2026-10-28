# v0.3.0 测试与验收记录

执行日期：2026-10-28。环境为 Windows、conda `agent`、Python 3.12.13；依赖版本、Git HEAD 和未提交状态见各次报告。本轮是未提交源码的开发验证，不能当作远程 CI 或正式发布证据。

## 最终结果

| 检查 | 实测结果 | 记录 |
| --- | --- | --- |
| 全部离线测试、Ruff 检查/格式、依赖检查 | **290 passed, 15 skipped**；其余检查全部通过 | [最终离线报告](offline-tests/20261028T034425501025Z/report.json)、[pytest 输出](offline-tests/20261028T034425501025Z/check-1.txt) |
| 最终解析器的 Gaia 公共查询复核 | **4 passed, 3 deselected**；编号、圆锥、质量筛选、当次确认无匹配 | [直接联网报告](live-gaia-direct-tests/20261028T034518068171Z/report.json) |
| 完整 Gaia 联网测试（含真实模型、名称和三工具） | **5 passed, 2 failed**；名称链路与三工具成功路径受 SIMBAD 超时阻塞 | [完整联网报告](live-gaia-tests/20261028T034043941186Z/report.json)、[模型精确源回答](live-gaia-tests/20261028T034043941186Z/model-source.json) |
| 十二项真实 HTTP 验收 | **9/12 passed**；失败项为名称 → Gaia、SIMBAD 回归、三工具成功路径 | [HTTP 报告](acceptance-v03/20261028T033915717761Z/report.json)、[服务日志](acceptance-v03/20261028T033915717761Z/uvicorn.txt) |
| HTTP 临时服务清理 | `server_stopped=true`、`server_port_closed=true`，报告记录 PID 和退出码 | 同上 |
| ESA 真实字段元数据 | 官方 BINARY2 响应，目录字段单位已核对，计算别名不附单位 | [元数据报告](gaia-metadata/20261028T033820264281Z/report.json)、[原始 VOTable](gaia-metadata/20261028T033820264281Z/cone.xml) |

最终公共查询复核在增加分配边界、BINARY2 掩码和单位写法回归后执行，不含模型、SIMBAD 或 ADS；不能用其 4 项通过代替完整联网成功。

## 已验证的行为

真实 HTTP 通过健康检查、Swagger HTML、OpenAPI 版本/字段、空输入、Gaia 精确源与距离、圆锥与关闭距离、质量筛选、经当次预检确认的无匹配，以及 ADS 回归。真实模型的精确源回答区分测量与程序距离近似，并说明视差零点未校正。

含 SIMBAD 的失败响应没有伪造坐标。名称链路停止；三工具场景保留成功的 Gaia 与 ADS 数据，返回 `partial`，失败的 SIMBAD 调用及来源时间逐次保留。独立短超时探测同一官方主机的入口、TAP capabilities 和 tables 也超时；这说明当次本机访问失败，不能据此断言全球服务宕机。

默认离线测试验证三类数据分流、来源去重、预算共享、批次预验证、后续模型失败保留数据、前 10 行模型视图与完整样本统计、严格参数/编号/单位、HTTP 错误、TAP 状态、外部 XML 引用、响应体/分配边界、BINARY2 掩码、缺失值/负误差、截断哨兵及近似距离条件。合成测试值不是观测记录。

## 保留的失败历史

- [首次离线通过](offline-tests/20261028T033613532970Z/report.json)：283 passed，15 skipped，后续增加了回归测试。
- 首轮 [联网测试输出](live-gaia-tests/20261028T033643204727Z/check-1.txt)：3 passed、4 failed，其中两项圆锥失败暴露 ESA 计算别名缺单位，另两项为 SIMBAD 超时；原响应与 JUnit 均保留。汇总打印遇到 Windows GBK 编码异常而中断，后续修复为 UTF-8；该轮不能当作正常完成的归档。
- [BINARY2 回归发现的问题](offline-tests/20261028T034344618441Z/report.json)：289 passed、1 failed、15 skipped。Astropy 写出无量纲单位为 `---`，补齐合法写法后最终离线 290 项通过。

所有旧记录保留原文件，不覆盖失败或其他版本。测试结束时尚未创建 v0.3 提交、远程 CI、标签或 Release。发布前仍需恢复 SIMBAD 访问并重新完成名称、回归、三工具成功路径及目标提交 CI。

## 发布前复核（2026-10-28）

用户已授权测试符合预期后直接发布；本轮重新执行离线与完整 Gaia 联网验收，尚未满足发布条件：

- [离线复核](offline-tests/20261028T035106246134Z/report.json)：290 passed、15 skipped，Ruff 检查/格式和依赖检查全部通过。
- [完整联网复核](live-gaia-tests/20261028T035108550097Z/report.json)：5 passed、2 failed。精确源、圆锥、筛选、无匹配和真实模型精确源通过；名称链路与三工具成功路径仍因 `simbad_timeout` 失败。
- [名称链路响应](live-gaia-tests/20261028T035108550097Z/model-name.json)：SIMBAD 未取到坐标，未凭模型记忆执行 Gaia 圆锥查询。
- [三工具响应](live-gaia-tests/20261028T035108550097Z/model-three-tools.json)：Gaia 与 ADS 成功结果保留，SIMBAD 超时，顶层 `partial`。这验证了降级行为，不能替代完整成功路径验收。

本机默认网络与现有本机 HTTP 代理对同一官方 SIMBAD 端点的只读探测均出现 TLS 读取超时；未修改全局代理、DNS、路由或 TLS 校验。该轮因联网门槛失败停止发布，未启动新 HTTP 验收服务，未创建提交、标签或 Release，未启动远程 CI。后续需恢复访问后补验，再通过目标提交的主分支和标签 CI。

## 再次重试（2026-10-28 12:44—12:47，北京时间）

用户要求重试后，再次执行完整 Gaia 联网验收：[本次报告](live-gaia-tests/20261028T044437028050Z/report.json)。结果仍为 **5 passed、2 failed**：Gaia 直接查询与真实模型精确源通过；名称链路和三工具成功路径仍因 SIMBAD TLS 握手阶段超时失败。失败记录完整保留，未放宽断言。发布门槛未满足，本轮未创建提交、标签、Release，也未启动临时 HTTP 服务。

同时完成 [源码与文档审计](source-audit/20261028T044618558455Z/report.json)：41 个文件形成 SHA-256 快照，未检出实际配置密钥，所检查文档的本地链接均有效。

## 官方镜像探测（2026-10-28）

查阅 [哈佛/CfA 官方镜像说明](https://simbad.cfa.harvard.edu/) 与本机 astroquery 0.4.11 的服务器配置后，测试了 `https://simbad.cfa.harvard.edu/simbad/`、该镜像的 TAP capabilities，以及 astroquery 列出的 `simbad.harvard.edu` 的 TAP capabilities。三项本机 HTTPS 只读探测均出现 `ReadTimeout`，约 9 秒结束；[原始探测报告](mirror-probe/20261028T063704808247Z/report.json) 保留 URL、超时设置、时间和错误类型。

这只证明当次本机也未能访问这些镜像入口，不能据此断言镜像全球不可用。未切换项目默认数据源，也未将失败探测当作联网验收成功。

## 带已知限制发布的授权

2026-10-28 用户明确要求“直接发布吧，可能是网站今天在维护”。据此，本版允许带已记录的 SIMBAD 外部连接失败发布；维护原因仍未确认。上述失败报告、未完成的成功路径和镜像探测结果全部保留，不修改为通过。离线测试、Ruff、依赖检查以及目标提交的主分支和标签 CI 仍需通过；发布说明明确列出限制。

发布范围为 v0.3 代码、文档与不可覆盖的测试记录；另行编写的 v0.4 规划及其 README 入口保留在工作区，不纳入该版本提交。

发布前最后一次 [离线复核](offline-tests/20261028T065347873370Z/report.json)：290 passed、15 skipped，Ruff 检查/格式和 `pip check` 全部通过。此处 15 项跳过为独立启用的联网测试，不代表联网验收成功。
