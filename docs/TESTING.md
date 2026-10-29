# 测试说明

## 准备与执行

在项目根目录使用 conda 的 `agent` 环境：

```powershell
conda activate agent
python -m pip install -e ".[dev]"
python -m pytest -q
```

当前实际结果见 [V0.6 测试记录](test-records/v0.6.0/README.md)，历史见 [V0.5](test-records/v0.5.0/README.md)、[V0.4](test-records/v0.4.0/README.md)、[V0.3](test-records/v0.3.0/README.md)、[V0.2](test-records/v0.2.0/README.md)。查看各项名称可使用 `python -m pytest -v`。离线测试通过 fixture 阻止外部 HTTP 请求，不会消耗模型额度。`scripts/run_tests.py` 默认强制关闭全部三个联网开关，避免继承终端设置误用真实服务。

## V0.6 网页手动测试

按README启动单worker后端及前端，访问 <http://127.0.0.1:5173/projects>。先在对话页取得一轮完整结果，再创建项目并加入该会话，保存命名快照。核对100行原始表、来源时间与条件，选择单条查询，检查确认弹窗；取消不触网，确认才生成独立重跑轮次与快照。选择新旧快照比较，查看执行状态和数据状态。

导出项目ZIP，再导入恢复，核对新项目ID、未认证标记、完整结果及关系。刷新选中的快照，再生成预览和单轮ZIP。最后删除恢复项目，确认其会话仍存在于未归档列表。使用独立测试库，避免试验性删除个人历史。

## V0.6 自动化检查

```powershell
conda activate agent
python scripts/run_tests.py
python scripts/verify_v06.py
$env:NODE_BINARY = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
python scripts/run_frontend_checks.py
python scripts/run_frontend_checks.py --browser
python scripts/verify_package.py
# 显式联网，会产生模型用量；真实服务失败如实保存
python scripts/verify_v06.py --live
```

浏览器验收前停止手动启动的8000/5173服务。HTTP脚本使用动态端口、合成服务及独立临时库，覆盖三工具直接重跑、幂等、100行、项目比较、固定成员/哈希、真实进程重启、运行重跑标中断且不自动重放，以及在另一份空库导入恢复和删除项目保留会话。Windows使用原生TCP监听表确认临时端口关闭，不把连接超时视为关闭证据。

`test_projects.py`覆盖完整快照、迁移前备份和故障回滚、修订冲突、来源等级保留、共享执行槽、配额、坏包与引用/版本/严格JSON、大小边界及导入失败无部分写入。默认禁止科研服务HTTP访问，导入/比较不调用模型。前端覆盖快照地址刷新恢复、明确重跑确认和Escape取消、原请求键、项目恢复与移动端布局；旧工作台浏览器用例同时执行。

`--live`实际检查Gaia/ADS/SIMBAD的初次模型查询和无模型直接重跑，复验名称链路与三工具，并用真实响应完成比较、包校验、新库恢复和图表再生成。接入哈佛镜像后本次21/21通过，原失败报告保留；版本化证据见V0.6记录。

## V0.5 前后端与会话验收

`test_conversations.py`覆盖完整结果保存、幂等先于修订检查、运行中202、不重复收费执行、跨标签冲突、全局两任务与旧聊天共享、失败记录、配额、SQLite迁移备份/回滚/高版本拒绝、重启中断、六轮/64 KiB上下文、纯历史解释不复制新结果、产物同包哈希/过期/损坏/删除以及本机Host/Origin/CORS和实际分块接收边界。

```powershell
python scripts/verify_v05.py
python scripts/run_frontend_checks.py
python scripts/run_frontend_checks.py --browser
python scripts/verify_package.py
python scripts/verify_v05.py --live
```

默认HTTP脚本显式启动 `scripts.fixture_server:app`，仅使用合成模型和数据源，正常应用入口不导入该模块。脚本创建专用临时SQLite库，检查100行、两轮实际参数继承、幂等、同包预览/下载、真实进程重启与运行中断、改名删除；停止自己创建的全部服务后再清理临时库。失败报告保留，不把合成数据当作观测。

前端需要Node24.15+（本轮24.22.1），从 `frontend/package-lock.json` 执行 `npm ci`；`vue-tsc`、零警告ESLint、Vitest、Vite生产构建与实际OpenAPI生成类型比对独立归档。`NODE_BINARY`可指定已有Node。测试依赖安装需要npm网络，测试的模型/数据库替身不访问外部科研服务。

浏览器测试使用真实生产 `dist/`、独立静态代理和合成API服务。Windows运行Chromium与已安装Edge，Linux仅Chromium；固定1440×900、390×844，记录实际浏览器版本、截图、下载ZIP与错误轨迹。覆盖输入法组字、键盘、历史恢复、完整表分页、图表/下载、重命名/删除确认、断线、纯文本HTML探针、固定代理目标及API不回退HTML。检查后验证8000/5173端口关闭，不复用未知已有服务。首次需在前端执行 `npx playwright install chromium`。

独立wheel脚本构建当前后端并安装到专用目录，确认实际导入路径不在源码树，检查无密钥API与失败持久化；依赖复用已验证的Python环境，不声称是全新依赖环境安装。前端不嵌入wheel，验证wheel不等于发布安装器。

`--live`使用真正的会话API、模型与科研服务，可能产生费用。逐项验证Gaia条件继承与新来源时间、ADS历史DOI、距离解释、SIMBAD名称链路及三工具，生成真实轮次产物并核对PNG/ZIP哈希。外部失败标为失败，不借用旧版豁免；本轮记录见V0.5入口。

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
| `test_ads.py` | 固定域名/字段/认证/排序/超时、关闭重试/重定向、严格参数边界、完整字段、去重、缺失与坏字段、分页矛盾、错误映射和密钥清理 |
| `test_literature_chat.py` | 双工具批次验证、共享预算、来源顺序、模型视图截断与原始数据保留、综合失败降级、恶意摘要样例、无 token 的 SIMBAD 回归及 OpenAPI |
| `test_gaia.py` | 严格模式/编号/边界、固定 ADQL 与 POST、单位、TAP 前后状态、XML 外部引用防护、响应体/分配上限、BINARY2 掩码、坏字段、截断/哨兵行及安全错误 |
| `test_analysis.py` | 合成样本统计、缺失与负/零视差、距离开关、跳过顺序、SNR=10、100 pc/5 pc 示例与极端有限值 |
| `test_gaia_chat.py` | 三类结果分流、来源去重与顺序、完整统计/API 和前 10 行模型视图、批次验证、共享预算、后续模型失败保留数据、配置与无网络初始化 |
| `test_exports.py` | 严格递归字段/有限数/状态/来源/统计复算，完整100行与跨查询上下文，CSV精度和文本保护，哈希与ZIP读回，三种图的坐标与PNG，分块超限、忙锁与失败释放，V0.3真实历史响应兼容、OpenAPI所有引用可解析 |

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

ADS 测试使用独立开关；需要 `ADS_API_TOKEN`、`DEEPSEEK_API_KEY` 与 ADS / SIMBAD / DeepSeek 网络访问：

```powershell
python scripts/run_tests.py --live-ads
# 或手动启用：
$env:ASTROAGENT_RUN_LIVE_ADS = "1"
try {
    python -m pytest tests/test_live_ads.py -v
} finally {
    Remove-Item Env:ASTROAGENT_RUN_LIVE_ADS -ErrorAction SilentlyContinue
}
```

固定 bibcode、主题年份、无匹配、真实模型 ADS 选择与综合调用均验证实际响应。合成的恶意摘要探针单独标明为模型防注入测试，不能充当真实 ADS 数据验收。原 `ASTROAGENT_RUN_LIVE` 不启用 ADS；显式启用后缺少凭证或外部服务失败会报错。

Gaia 使用独立开关；直接公共查询无需密钥，真实模型用例需要 `DEEPSEEK_API_KEY`，三工具用例另需 `ADS_API_TOKEN`：

```powershell
python scripts/run_tests.py --live-gaia
# 或仅检查公共 Gaia 查询：
$env:ASTROAGENT_RUN_LIVE_GAIA = "1"
try {
    python -m pytest tests/test_live_gaia.py -k "not model" -v
} finally {
    Remove-Item Env:ASTROAGENT_RUN_LIVE_GAIA -ErrorAction SilentlyContinue
}
```

三个开关互不启用；`--live-gaia` 仅运行 Gaia 测试文件，涵盖精确源、小圆锥、质量筛选、当次确认的空结果、真实模型、SIMBAD 名称衔接和三工具联合。显式启用后的外部错误按失败保存。归档入口将真实输入与完整结构化结果保存为独立 JSON；不能以离线模型测试代替真实解释验收。

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
| `python scripts/run_tests.py --live-ads` | `live-ads-tests` | 独立 ADS 与综合聊天的真实测试、JUnit XML、JSON 汇总 |
| `python scripts/run_tests.py --live-gaia` | `live-gaia-tests` | 7 项 Gaia / 真实模型 / 名称链路 / 三工具检查，输入与结果 JSON、JUnit、汇总 |
| `python scripts/verify_live.py` | `acceptance` | `report.json` 与 `uvicorn.txt` |
| `python scripts/verify_v02.py` | `acceptance-v02` | 九项真实 HTTP 检查、请求和完整响应、依赖版本、服务停止状态 |
| `python scripts/verify_v03.py` | `acceptance-v03` | 十二项真实 HTTP 检查、当次空结果预检、查询条件/完整响应、Git/依赖信息、进程停止和端口关闭证据 |
| `python scripts/verify_v04.py` | `acceptance-v04` | 无密钥合成数据导出、三种图/单点跳图/部分失败/无匹配、真实Uvicorn分块超限、ZIP下载与逐文件哈希、PID退出及端口关闭 |
| `python scripts/verify_v04.py --live` | `live-export-tests` | 当次Gaia圆锥/精确源、SIMBAD、ADS、名称及三工具查询→导出，保存请求/响应、ZIP、PNG、清单与失败记录 |
| `python scripts/measure_latency.py` | `latency` | 逐次响应时间、成功状态与汇总 JSON |

延迟测试默认对 `http://127.0.0.1:8000` 执行 5 次健康检查和 3 次 Betelgeuse 查询；可通过 `--samples`、`--health-samples` 和 `--base-url` 调整。需要先启动服务，会产生模型用量。

V0.2 HTTP 脚本检查健康、文档、OpenAPI、空输入、仅 SIMBAD、仅 ADS、综合查询与两类无匹配。失败的请求/响应也保存；`finally` 中停止自己创建的服务。不可覆盖的主报告在分版本目录，本机便利副本为忽略提交的 `outputs/v0.2-acceptance.json`，不覆盖 V0.1 记录。

原有 `outputs/v0.1-acceptance.json`、`outputs/uvicorn-acceptance.log` 和 `outputs/latency-check.json` 已原样归档到 [v0.1.0 记录](test-records/v0.1.0/README.md)，并逐文件校验 SHA-256。归档目录的 `archive.json` 保留原路径、测试时间和校验值；旧文件仍保留在本机 `outputs/`，后续运行使用新目录。

V0.3 HTTP 脚本实际启动 Uvicorn，检查基础接口、Gaia 两种查询、质量筛选、距离开关、无匹配、名称衔接、SIMBAD/ADS 回归与三工具联合。先用最多 3 次有界精确查询确认空结果条件；预检失败时不能把无匹配项判为通过。`finally` 停止临时服务，并核对 PID 退出和端口不再监听。失败响应与日志原样保存，不放宽断言或覆盖历史报告。

归档器记录 Python/依赖版本、开始结束 UTC 时间、Git HEAD 与工作区状态；开发阶段记录的 `git_dirty=true` 表示对未提交源码的验证，不能当成某个已发布提交的 CI 证据。Windows 控制台输出按 UTF-8 处理，避免真实论文文字使记录脚本中断。

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

V0.4 两种 HTTP 脚本运行模式均在 `finally` 停止自身服务并检查 PID 和端口。默认模式强制清空子进程的模型及 ADS 密钥，合成数据明确标记，不能作为实际观测；`--live` 需要实际凭证和外部网络，外部失败按失败记录，不得静默跳过。PNG 解码/尺寸检查不等同于视觉验收；人工打开实际 PNG 后，在独立 `figure-review/<UTC时间>/` 保存图像哈希与检查结论，原报告的 `pending_manual_inspection` 不覆盖修改。

当前验证了服务提供 Swagger HTML 和正确 OpenAPI 定义，未在图形浏览器中检查 Swagger CDN 静态资源加载。模型的自然语言回答仍需对照 `results` 核查；本版本没有完整的模型科学准确性评测、压力测试或生产部署验收。


## SIMBAD 镜像故障转移复验

主站网络不可达、超时或临时服务故障时自动尝试固定的哈佛镜像，不修改全局astroquery配置；未匹配、无效查询和损坏数据不换站重放。`test_simbad_fallback.py`覆盖实际来源、独立会话、包装异常、两站失败、并发和无匹配；原首次capabilities请求的有界超时测试保留。真实测试接受两站的准确来源域名，坐标和工具返回断言保持。

2026-10-29本次离线417项通过，真实SIMBAD两项回归和V0.6联网21项均通过；名称链路另核对实际SIMBAD坐标与Gaia参数一致，三工具确有三类新结果。`--live`日志中的30秒线程栈是诊断采样，并非断言失败，最终结果与JUnit为准。历史失败不覆盖。
