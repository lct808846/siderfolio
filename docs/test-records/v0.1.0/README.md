# v0.1.0 测试记录

| 类型 | 原测试时间（北京时间） | 结果 | 原始记录 |
| --- | --- | --- | --- |
| 真实 HTTP 功能验收 | 2026-10-26 19:09 | 六项检查通过，临时服务已停止 | [JSON](acceptance/20261026T110938318990Z/report.json)、[服务日志](acceptance/20261026T110938318990Z/uvicorn.txt) |
| 真实查询延迟 | 2026-10-26 19:19 | 查询 3 次平均 5.2691 秒；健康检查 5 次平均 6.8 毫秒 | [JSON](latency/20261026T111909735226Z/report.json) |
| 离线回归与代码检查 | 2026-10-26 19:25 | 42 通过、2 跳过，Ruff 和依赖检查通过 | [JSON](offline-tests/20261026T112501898813Z/report.json)、[JUnit XML](offline-tests/20261026T112501898813Z/pytest.xml)、[测试输出](offline-tests/20261026T112501898813Z/check-1.txt) |
| 发布前检查 | 2026-10-26 19:33 | 42 通过、2 跳过，Ruff 和依赖检查通过 | [JSON](offline-tests/20261026T113344647924Z/report.json)、[JUnit XML](offline-tests/20261026T113344647924Z/pytest.xml)、[测试输出](offline-tests/20261026T113344647924Z/check-1.txt) |

初次版本验收还记录了 `42 passed, 2 skipped in 3.69s` 的离线测试、`2 passed in 16.69s` 的联网测试，以及通过的 Ruff 和依赖检查；当时没有保存独立终端日志，这些数字来自本次开发时记录的验收摘要。后续用 `scripts/run_tests.py` 执行会同时保存原始终端输出和 JUnit XML。

延迟数据是同一问题的少量串行完整响应时间，不代表并发性能或 P95/P99。时间目录以 UTC 命名，文件中的时间和数值保持原样。
