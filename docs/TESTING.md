# 测试说明

## 准备与执行

在项目根目录使用 conda 的 `agent` 环境：

```powershell
conda activate agent
python -m pip install -e ".[dev]"
python -m pytest -q
```

当前预期结果：42 项离线测试通过，2 项真实服务测试默认跳过。查看各项名称可使用 `python -m pytest -v`。离线测试通过 fixture 阻止外部 HTTP 请求，不会消耗模型额度。

代码检查：

```powershell
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m pip check
```

## 自动化覆盖范围

| 测试 | 验证内容 |
| --- | --- |
| `test_health_without_deepseek_key` | 移除进程内的 `DEEPSEEK_API_KEY` 后，`GET /health` 仍返回 HTTP 200、JSON 内容类型及精确响应 `{"status": "ok"}` |
| `test_swagger_ui_is_available` | `/docs` 返回 HTTP 200 和 HTML，并引用 OpenAPI 定义 |
| `test_health_is_documented_in_openapi` | `/openapi.json` 正常返回，包含应用名称及 `GET /health` 的成功响应定义 |
| `test_chat.py` | 模型工具调用与 ToolMessage 回传、来源记录、概念问答、多目标部分成功、无匹配、输入验证、配置错误、认证/限流/超时/网络错误、无效工具与参数、空回答、调用次数和轮数上限、保留已有结果、聊天 OpenAPI |
| `test_simbad.py` | Astropy 表转 JSON、ICRS 坐标单位、来源 URL 编码、缺失/掩码/非有限值、不匹配、超时包装、连接失败、无效返回、元数据网络超时限制 |
| `test_config.py` | `.env` 加载与环境变量优先级、密钥 repr 隐藏、模型超时/关闭重试/非思考模式/工具注册 |

接口测试使用 FastAPI `TestClient` 在进程内发起请求；工具转换测试使用合成数据，不将它当作真实天文数据，也不将模拟测试当作联网验收。默认测试不验证模型的实际行为或远端服务可用性。

## 真实服务测试

需要配置 `DEEPSEEK_API_KEY` 并能够连接 DeepSeek、SIMBAD。显式启用：

```powershell
$env:ASTROAGENT_RUN_LIVE = "1"
python -m pytest tests/test_live.py -v
Remove-Item Env:ASTROAGENT_RUN_LIVE
```

两项测试分别验证真实 SIMBAD Betelgeuse 查询，以及真实模型自动调用工具、拿到坐标并生成回答。会产生模型 API 用量，失败时不会跳过或自动使用模拟数据。

这些是外部依赖的抽样验收，不能保证之后每次网络查询都成功。

## 手动运行验收

在已激活环境的终端启动：

```powershell
python -m uvicorn astroagent.main:app --host 127.0.0.1 --port 8000
```

在另一个 PowerShell 终端执行：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

应显示 `status` 为 `ok`。浏览器打开 `http://127.0.0.1:8000/docs`，可执行 `GET /health` 和 `POST /api/v1/chat`。提交 `{"message":"请查询 Betelgeuse 的坐标和天体类型，并给出来源。"}`，确认 `results` 包含实际数据、`sources` 包含 SIMBAD 链接。完成后按 `Ctrl+C` 停止。

自动进行真实 HTTP 验收并停止临时服务：

```powershell
python scripts/verify_live.py
```

该脚本选择临时本机端口，检查 `/health`、`/docs`、`/openapi.json`、空白输入、Betelgeuse 完整查询和不存在的名称，再停止自己启动的服务。报告包括真实回答、结构化结果、来源、UTC 时间、依赖版本和进程停止状态。

## 按版本保存记录

记录统一放在 `docs/test-records/v<版本>/<类型>/<UTC运行时间>/`，可随 Git 保存。同一版本重复执行会新建目录，已有记录不覆盖。普通测试和验收使用 `pyproject.toml` 版本，延迟测试使用被测服务 `/openapi.json` 中的版本。

| 命令 | 类型 | 保存内容 |
| --- | --- | --- |
| `python scripts/run_tests.py` | `offline-tests` | pytest、Ruff、pip check 输出，JUnit XML，JSON 汇总 |
| `python scripts/run_tests.py --live` | `live-tests` | 真实服务测试输出，JUnit XML，JSON 汇总 |
| `python scripts/verify_live.py` | `acceptance` | `report.json` 与 `uvicorn.txt` |
| `python scripts/measure_latency.py` | `latency` | 逐次响应时间、成功状态与汇总 JSON |

延迟测试默认对 `http://127.0.0.1:8000` 执行 5 次健康检查和 3 次 Betelgeuse 查询；可通过 `--samples`、`--health-samples` 和 `--base-url` 调整。需要先启动服务，会产生模型用量。

原有 `outputs/v0.1-acceptance.json`、`outputs/uvicorn-acceptance.log` 和 `outputs/latency-check.json` 已原样归档到 [v0.1.0 记录](test-records/v0.1.0/README.md)，并逐文件校验 SHA-256。归档目录的 `archive.json` 保留原路径、测试时间和校验值；旧文件仍保留在本机 `outputs/`，后续运行使用新目录。

## V0.1 验收记录

- 日期：2026-10-26。
- 环境：conda `agent`，Python 3.12.13，pytest 9.1.1；FastAPI 0.141.1、LangChain Core / OpenAI 1.6.0、astroquery 0.4.11。
- 安装：项目可编辑安装成功，`pip check` 未发现依赖冲突。
- 离线测试：`42 passed, 2 skipped in 3.69s`。
- 显式联网测试：`2 passed in 16.69s`，真实 SIMBAD 与真实 DeepSeek 工具调用均成功。
- 实际服务：`verify_live.py` 六项真实 HTTP 检查通过；报告生成于北京时间 2026-10-26 19:09，临时服务已停止。
- Betelgeuse 实测：主标识符 `* alf Ori`；ICRS 赤经 `88.79293899077537` 度、赤纬 `7.407063995272694` 度；类型代码 `s*r`；光谱类型 `M1-M2Ia-Iab`；坐标文献编号 `2007A&A...474..653V`。这些值来自当次查询，不写死在应用中。
- 无效名称实测：返回 HTTP 200、顶层 `status=error`、`results[0].status=not_found`、`data=null`、`sources=[]`，自然语言回答明确说明无匹配。
- Ruff 代码和格式检查通过；GitHub Actions 已配置，尚未推送触发远程运行。
- 执行说明：沙箱内的 TestClient 未正常返回，已停止该次测试；上述通过结果来自本机 `agent` 环境的受控沙箱外验证。联网验收需要外网访问。

## 验证边界

当前验证了服务提供 Swagger HTML 和正确 OpenAPI 定义，未在图形浏览器中检查 Swagger CDN 静态资源加载。模型的自然语言回答仍需对照 `results` 核查；本版本没有完整的模型科学准确性评测、压力测试或生产部署验收。
