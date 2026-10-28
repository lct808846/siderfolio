# 分版本测试记录

按 `v<版本号>/<测试类型>/<UTC运行时间>/` 保存；同一版本多次运行各有独立目录，历史记录不覆盖。版本来自 `pyproject.toml`；延迟测试读取被测服务的 OpenAPI 版本，避免误归档到本地代码的版本。

当前代码版本：[v0.3.0](v0.3.0/README.md)。历史版本：[v0.2.0](v0.2.0/README.md)、[v0.1.0](v0.1.0/README.md)。

```powershell
python scripts/run_tests.py                 # 离线测试、Ruff、依赖检查
python scripts/run_tests.py --live          # 真实 SIMBAD / DeepSeek 测试
python scripts/run_tests.py --live-ads      # 独立 ADS / 综合查询测试
python scripts/run_tests.py --live-gaia     # 独立 Gaia / 真实模型 / 三工具测试
python scripts/verify_v03.py                # V0.3 真实 HTTP 验收
python scripts/verify_v02.py                # V0.2 真实 HTTP 验收
python scripts/verify_live.py               # 临时服务的真实 HTTP 验收
python scripts/measure_latency.py           # 已启动服务的延迟，默认 3 次查询
```

后三个命令会访问真实外部服务，并可能产生模型用量。JSON 报告、JUnit XML 和文本日志可随 Git 保存。已有旧报告原样归档；目录里的 `archive.json` 记录原路径与 SHA-256，保留原始测试时间和测量值。`outputs/` 继续用于本机运行进程和临时产物。
