# v0.2.0 测试记录

日期：2026-10-26。环境为 Windows、conda `agent`、Python 3.12.13；应用和可编辑安装元数据均为 `0.2.0`。FastAPI 0.141.1、LangChain Core / OpenAI 1.6.0、astroquery 0.4.11、requests 2.34.2。

## 本机验收

| 检查 | 实际结果 | 记录 |
| --- | --- | --- |
| 离线自动化 | 147 passed、8 skipped；Ruff 检查与格式检查通过，pip check 无冲突 | [发布前复验](offline-tests/20261026T122342987210Z/report.json)、[pytest 输出](offline-tests/20261026T122342987210Z/check-1.txt) |
| 真实 ADS 与综合聊天 | 6 passed：固定 bibcode、主题年份、无匹配、真实模型 ADS 选择、SIMBAD 联合查询，以及真实模型对合成恶意摘要的探针 | [最终汇总](live-ads-tests/20261026T120749586866Z/report.json)、[输出](live-ads-tests/20261026T120749586866Z/check-1.txt) |
| V0.1 真实服务回归 | 2 passed：SIMBAD Betelgeuse、DeepSeek 自动工具调用 | [汇总](live-tests/20261026T120250374162Z/report.json)、[输出](live-tests/20261026T120250374162Z/check-1.txt) |
| 真实 HTTP | 最终 9/9 通过，临时 Uvicorn 已停止；含真实请求、完整响应、检索式与 UTC 时间 | [最终报告](acceptance-v02/20261026T122019496830Z/report.json)、[服务日志](acceptance-v02/20261026T122019496830Z/uvicorn.txt) |
| ADS 网页链接 | 路由形式按官方前端源码核对；内置浏览器触发人工验证，结果页未图形验收 | [观察记录](ui-link-check/20261026T120835835467Z/report.json) |

运行命令：

```powershell
python scripts/run_tests.py
python scripts/run_tests.py --live-ads
python scripts/run_tests.py --live
python scripts/verify_v02.py
```

普通 `pytest` 默认跳过联网组，离线 fixture 阻止外部 HTTP；真实组显式启用后失败即报错。Windows 沙箱内 `TestClient` 在 `socketpair` 初始化处挂起，该次进程已停止；表中完整检查来自受控的本机环境执行，不将挂起运行当作通过。

## 核查结果和边界

真实固定 bibcode `2007A&A...474..653V` 返回《Validation of the new Hipparcos reduction》，作者 van Leeuwen, F.，2007 年，ADS 返回了标题、摘要及 DOI。该例数据来自当次 ADS 响应，未写死到应用中。联合查询的坐标与论文分别有 SIMBAD 和 ADS 来源。

HTTP 报告验证了两类无匹配均保留尝试记录、顶层 `error` 且 `sources=[]`。缺 token、认证错误、限流、超时、坏字段/分页与后续模型失败由离线测试覆盖，未故意消耗真实账户配额制造限流。

六项联网测试运行 137.98 秒，全部通过，但曾输出 SIMBAD 首次 TAP capabilities 网络等待的 30 秒诊断栈。由此发现构造时传入 timeout 会先联网，再安装受限 session；已改为无 timeout 构造、先注入受限 session、再设置 timeout，并新增首次请求回归测试。最终离线与后续 HTTP 验收包含这一修正。

修正后的第一轮 HTTP 验收遇到真实 SIMBAD 波动：综合查询中的 SIMBAD 返回 `simbad_unavailable`，ADS 成功数据完整保留且顶层为 `partial`；无效天体查询返回 `simbad_timeout`，没有误报无匹配。该轮 7/9 通过、进程已停止，[失败报告](acceptance-v02/20261026T121214590921Z/report.json) 原样保留；没有将异常改成模拟成功或放宽验收断言。

下一轮 8/9 通过：首次 SIMBAD 超时后，模型再次调用查询成功，程序保留两次结果并返回 `partial`，因此严格成功断言仍未通过；[该轮报告](acceptance-v02/20261026T121628737110Z/report.json) 保留。恢复后的最终一轮于北京时间 2026-10-26 20:20 开始，九项全部通过，服务已停止。未删除失败结果或扩大超时来替代默认配置验收。

已将用户提供的 ADS token 保存为当前 Windows 用户环境变量；凭证不写入仓库和测试记录。已打开的 Codex、终端或服务需要重新加载变量或重启才能继承更新。真实测试的模型 API 使用已获本次版本开发授权。

ADS 图形结果页受人工验证阻挡，未尝试验证码。网页链接是复查入口，结构化结果保留的检索式、筛选、分页和排序是实际 API 条件。Swagger HTML 和 OpenAPI 已验收，未单独验收浏览器中的 CDN 资源加载。

远程 CI 独立于本机记录，发布时需核对标签对应提交通过；最终运行链接与提交号见 [GitHub Release](https://github.com/lct808846/astroagent/releases/tag/v0.2.0)。本次未包含生产部署、压力测试或完整科研准确性评测。模型注入样例只能验证特定行为，不能证明排除了全部提示注入风险。
