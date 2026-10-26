# AstroAgent 开发文档 V0.2：ADS 文献检索

**文档日期：** 2026-10-26  
**文档状态：** 已实现；开发契约及验收依据（2026-10-26 更新）\
**前置版本：** V0.1，SIMBAD 天体查询  
**本次目标：** 在现有单次、无状态 Agent 中接入 ADS，让用户通过自然语言检索真实文献，并取得可核查的书目信息、摘要和来源。

本文延续 [V0.1 项目计划](PROJECT_PLAN_V0.1.md) 的迭代方向。应用与包版本已更新为 `0.2.0`，M1–M5 已完成；以下内容保留为实现契约。实际测试结果见 [V0.2 记录](test-records/v0.2.0/README.md)，V0.1 范围亦已回归。ADS 图形搜索页受人工验证拦截，具体边界见发布说明。

## 1. 版本范围

### 1.1 必须实现

- 保留现有 SIMBAD 查询、接口路径、输入格式和错误响应结构。
- 新增 `search_ads` 工具，使用 ADS Search API 检索真实文献。
- 支持主题、标题、作者、年份范围和指定 bibcode 检索；支持相关性、发表时间、被引次数排序。
- 返回 bibcode、标题、作者、年份、出版物、DOI、摘要、被引次数及 ADS 页面链接；缺失字段不由模型补写。
- 支持一次请求同时查询天体信息与相关文献，保留每次工具调用的实际结果。
- 对无结果、配置缺失、认证失败、限流、超时和异常响应提供明确反馈。
- 增加离线自动化测试、显式联网测试及真实 HTTP 验收方案。

### 1.2 本版不包含

Gaia 查询、全文或 PDF 下载与解析、BibTeX 导出、RAG、向量数据库、多 Agent、MCP、前端、用户系统、跨请求会话记忆、后台任务、生产部署。本版也不建立论文质量评分或自动判断研究创新性。

文献总结只基于本次返回的书目信息与摘要。检索得到论文不等于读过全文，摘要不支持的实验细节和结论不能补写。

## 2. 使用场景与预期行为

| 场景 | 输入示例 | 预期行为 |
| --- | --- | --- |
| 主题检索 | 找 5 篇关于双星团与外部潮汐场的论文 | 调用 ADS，列出实际检索式、文献及链接；交代检索词翻译 |
| 年份筛选 | 检索 2020—2026 年 Betelgeuse 变暗相关论文，按时间排序 | 使用明确年份范围和日期降序，说明只是所取的一页 |
| 作者或标题检索 | 查找标题包含 binary star clusters 的论文 | 使用相应 ADS 字段，不把一般关键词匹配描述为精确标题匹配 |
| 指定文献 | 查询 bibcode 为 2007A&A...474..653V 的文献信息 | 通过 ADS 实际检索，不仅从 SIMBAD 文献编号生成书目信息 |
| 综合查询 | 查询 Betelgeuse 坐标，再找 3 篇有关其变暗的论文 | 分别调用 SIMBAD 与 ADS，区分坐标来源和文献来源 |
| 无匹配 | 查找一个无匹配的主题或编号 | 记录 `not_found`，不生成虚构文献 |
| 名称含糊 | 帮我找王老师最近的论文 | 在当前回答中请求补充姓名或范围；下一次请求须包含完整条件 |

“最近三年”等相对时间按请求时的 UTC 日期解释，在回答中给出实际采用的起止年份；若用户明确指定时区，则按该时区解释。不得把本文日期固定写入运行时提示词。

## 3. 现有实现与改动位置

| 位置 | V0.1 实现 | V0.2 改动（已实现） |
| --- | --- | --- |
| `src/astroagent/agent.py` | 仅注册并校验 `query_simbad`，循环内固定执行 SIMBAD | 注册两个工具，按工具名验证参数并分发；两个工具共享调用预算 |
| `src/astroagent/schemas.py` | `Source.name` 仅允许 SIMBAD；`QueryResult` 仅表示天体查询 | 扩展来源名称，新增文献参数、文献数据、检索结果模型和响应字段 |
| `src/astroagent/config.py` | DeepSeek 与 SIMBAD 配置 | 新增可选 ADS token 和查询超时 |
| `src/astroagent/api/chat.py` | 每次请求构造 Agent 与 SIMBAD 服务 | 注入 ADS 服务，更新描述；不在依赖构造阶段强制要求 ADS token |
| `src/astroagent/ads.py` | 无 | 新增 ADS HTTP 请求、字段转换、来源构建及错误映射 |
| 测试与文档 | V0.1 测试、配置示例与验收脚本 | 增加 ADS 测试、升级说明和独立 V0.2 验收产物 |

沿用 Python、FastAPI、LangChain、Pydantic 和已声明的 `requests`。ADS 直接通过 HTTP 调用，不为本版新增 ADS SDK、数据库或编排框架。同步查询继续在线程池中的聊天路由执行。

## 4. ADS 接口与配置

### 4.1 外部服务约定

调用 `GET https://api.adsabs.harvard.edu/v1/search/query`，凭证仅放入 `Authorization: Bearer <token>` 请求头。账号创建与 token 获取以 [ADS 官方开发仓库的 Access 说明](https://github.com/adsabs/adsabs-dev-api#access) 为准。

使用 HTTP 客户端的 `params` 编码参数，不拼接用户提供的 URL。API 的 `q`、`fl`、`rows`、`start`、`sort` 及响应格式依据 [官方 Search API 示例](https://github.com/adsabs/adsabs-dev-api/blob/master/API_documentation_Python/Search_API_Python.ipynb)。

固定请求字段：

```text
bibcode,title,author,year,pub,doi,abstract,citation_count
```

本版固定 `fq=database:astronomy`，并在结果中记录该过滤条件。不默认排除预印本或会议记录；用户要求同行评审时，可在 `q` 中加入 `property:refereed`。筛选语法参考 [ADS 检索语法](https://ui.adsabs.harvard.edu/help/search/search-syntax)。

### 4.2 新增环境变量

| 变量 | 默认值 | 验证与行为 |
| --- | --- | --- |
| `ADS_API_TOKEN` | 空 | 使用 `SecretStr` 保存；只有执行 ADS 工具时才检查非空 |
| `ADS_TIMEOUT_SECONDS` | `20` | 浮点数，`0 < value <= 120`；作为连接与读取超时传入 |

超时按网络操作计算，不是聊天总时限；不增加自动重试。关闭跨站重定向，避免带 token 的请求被转发至其他站点。外部地址固定在服务层，不接受工具参数修改。

保留原有 `AGENT_MAX_ROUNDS=4` 与 `AGENT_MAX_TOOL_CALLS=6`；SIMBAD 和 ADS 合计计数，不给 ADS 单独增加隐藏预算。达到上限时沿用已有降级机制。

`.env.example` 开发时增加空 token 示例。健康检查、离线测试和仅使用 SIMBAD 的请求无需 ADS token。非法超时配置仍按现有 Settings 验证返回 `invalid_configuration`；“ADS 可选”指 token 可留空，不代表忽略错误配置。

ADS 配额按实际响应头和账户权限判断，不硬编码每日额度；官方说明见 [Access Settings](https://github.com/adsabs/adsabs-dev-api#access-settings)。禁止把 token、Authorization 请求头、原始异常或含凭证的调试日志返回给用户。

## 5. 工具设计

### 5.1 `search_ads` 参数

新增 `LiteratureQuery`，沿用 `extra="forbid"` 和字符串首尾空白清理。

| 参数 | 类型 | 默认值 | 规则 |
| --- | --- | --- | --- |
| `query` | `str` | 必填 | ADS 检索式；非空，原始字符及单独 URL 编码后的值均不超过 1000 字符 |
| `rows` | `int` | `5` | 严格整数，范围 1–10 |
| `start` | `int` | `0` | 严格整数，范围 0–90；且 `start + rows <= 100` |
| `sort` | 枚举 | `relevance` | 仅允许 `relevance`、`date_desc`、`citation_count_desc` |

以上数量和分页限制是 AstroAgent 的产品限制。工具每次只请求一页，不自动翻页，不声称穷尽检索；请求更多结果时由用户缩小条件或明确页码，仍受调用预算约束。

排序映射：`relevance` 省略外部 `sort` 参数，`date_desc` 对应 `date desc`，`citation_count_desc` 对应 `citation_count desc`。按日期排序使用 ADS 的 `date`，不以 bibcode 字典序替代。

工具调用示例，表示设计输入，不是联网执行记录：

```json
{
  "query": "abs:(\"binary star clusters\") AND year:2020-2026",
  "rows": 5,
  "start": 0,
  "sort": "date_desc"
}
```

建议模型优先构造 `abs:`、`title:`、`author:`、`year:`、`bibcode:` 查询。`abs:` 涵盖标题、摘要与关键词，不能表述为只查摘要。天体名称全文关键词匹配与 `object:` 的对象关联检索含义不同，必须说明实际使用方式，不静默替换。完整检索式作为数据交给 ADS 解析；本地参数验证不承诺完整校验 ADS 语法，远端拒绝时返回明确错误。

### 5.2 执行流程

1. 模型返回工具调用；先校验整个批次的工具名、调用 ID 和各自参数，再执行该批次。
2. 根据名称调用 `SimbadService.query(...)` 或 `AdsService.search(...)`。
3. ADS 服务检查 token、构造固定域名请求、执行单次查询并验证返回结构。
4. 将标准化结果加入对应列表，再用匹配 `tool_call_id` 的 `ToolMessage` 返回模型。
5. 模型基于成功结果生成回答，程序汇总状态、来源和警告。
6. 后续模型失败或预算耗尽时，保留两类已执行结果并返回明确降级提示。

`create_model` 必须一次绑定两个工具。未知工具或无效参数继续使用 `model_invalid_tool_call`；不能只修改提示词而保留当前仅接受 `query_simbad` 的分发判断。

## 6. 数据模型与 API 兼容

### 6.1 接口约定

继续使用 `POST /api/v1/chat`，请求仍只有 `message`，保持 1–4000 字符及拒绝额外字段的约定。本版不增加独立文献路由。

响应保留 `status`、`answer`、`results`、`sources`、`warnings`，新增默认值为 `[]` 的 `literature_results`。`results` 继续仅存放原有 `QueryResult`；不要混入形状不同的文献数据。

`Source.name` 扩展为 `Literal["SIMBAD", "ADS"]`，现有 SIMBAD 序列化保持不变。此方案是字段增量扩展，但严格拒绝未知响应字段或只接受 SIMBAD 来源枚举的客户端仍需升级；发布说明必须交代这个兼容边界。

### 6.2 `LiteratureSearchResult`

每次实际执行的 ADS 调用生成一条结果，包括失败调用。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `query` | `str` | 实际送出的 ADS 检索式，不用原始中文问题代替 |
| `filters` | `list[str]` | 固定包含 `database:astronomy` |
| `rows` / `start` / `sort` | 与参数相同 | 记录实际分页与排序条件 |
| `status` | `success / not_found / error` | 当前检索状态 |
| `total_found` | `int \| null` | ADS `numFound`；未知或失败为 `null`，无匹配为 `0` |
| `returned_count` | `int` | 去重后的 `papers` 长度 |
| `has_more` | `bool \| null` | 有效响应按 `start + 原始 docs 数量 < total_found` 计算；失败为 `null` |
| `papers` | `list[PaperData]` | 本页文献，失败或无匹配为 `[]` |
| `source` | `Source` | ADS 搜索页链接及本次查询尝试的 UTC 时间 |
| `error` | `ErrorInfo \| null` | 失败原因；无匹配不作为服务异常，值为 `null` |

搜索页使用固定 ADS UI 域名，由程序编码 `q`、过滤条件、页偏移和排序参数构造；在实现阶段核对 UI 参数并测试可打开性。搜索页是复查入口，实际请求参数以本结果字段为准。

`numFound=0` 是 `not_found`；`numFound>0` 但请求页为空也记为 `not_found`，回答必须区分“本页为空”和“整个检索无匹配”。若服务端返回的 docs 超过请求条数，或分页元数据相互矛盾，应作为无效响应处理，不能静默截掉后声称完整。

### 6.3 `PaperData`

| 字段 | 类型 | ADS 映射与约定 |
| --- | --- | --- |
| `bibcode` | `str` | 必须为非空标识符，作为本页去重键；不强制某种期刊格式 |
| `title` | `str \| null` | `title` 数组首个非空标题；没有标题则为 `null` |
| `authors` | `list[str]` | `author` 数组；保留顺序，无数据为 `[]` |
| `year` | `int \| null` | `year` 的有效年份转换，无数据为 `null` |
| `publication` | `str \| null` | `pub`，不从 bibcode 猜测期刊 |
| `doi` | `list[str]` | 保留全部 DOI；缺失为 `[]`，不虚构 DOI |
| `abstract` | `str \| null` | 本次 ADS 返回的原始摘要，无数据为 `null` |
| `citation_count` | `int \| null` | 非负整数，保留真实 `0`，缺失不写成 `0` |
| `source` | `Source` | `name="ADS"`，程序由编码后的 bibcode 生成摘要页链接，时间沿用本次检索 |

单页重复 bibcode 保留第一条，不合并模型猜测的字段；每次调用的结果独立保留，不对跨调用结果列表去重。出现缺失 bibcode、字段类型错误或非 JSON 等异常时，整次 ADS 调用返回 `ads_invalid_response`，不静默丢弃坏记录。

成功响应的缺失可选字段按上表返回空值；存在但格式损坏的字段须与正常缺失区分。来源链接固定为 `https://ui.adsabs.harvard.edu/abs/{编码后的 bibcode}/abstract`，不使用模型生成的外链。

### 6.4 来源与顶层状态

顶层 `sources` 汇总成功 SIMBAD 查询来源和成功 ADS 返回的各篇论文来源，按 URL 去重并保留首次出现顺序。ADS 搜索页仍保留在每条 `literature_results[].source` 中；失败和无匹配的查询尝试不能进入成功来源列表。

状态按两个结果列表合计判定，延续 V0.1 的查询结果语义：

| 条件 | 顶层 `status` |
| --- | --- |
| 没有工具结果，模型正常完成概念回答或澄清 | `success` |
| 所有已执行查询均为 `success` | `success` |
| 有成功结果，也有 `not_found` 或 `error` | `partial` |
| 已执行查询全部为 `not_found` 或 `error` | `error` |
| 已有成功结果，但回答生成失败或达到调用限制 | `partial`，增加 `warnings` |

已执行查询全部失败且随后模型失败时，保留顶层 `error` 并增加警告。正常分页或缺少可选字段不自动变为 `partial`，但回答须说明未取得的数据和结果范围。

## 7. 错误与降级

ADS 的可预期失败统一包装成 `LiteratureSearchResult(status="error")`；聊天在得到工具结果后使用 HTTP 200，具体成功与否由顶层及逐条状态表示。这与现有 SIMBAD 数据库失败的处理保持一致。

| 情况 | 结果 `error.code` | `retryable` | 行为 |
| --- | --- | --- | --- |
| ADS token 未配置 | `ads_not_configured` | `false` | 不发送网络请求；提示服务端配置 |
| ADS HTTP 401 / 403 | `ads_authentication_failed` | `false` | 提示凭证或权限问题，不回显外部响应体 |
| ADS HTTP 429 | `ads_rate_limited` | `true` | 提示稍后重试；本次不自动重试 |
| 连接或读取超时 | `ads_timeout` | `true` | 返回超时说明，保留其他工具结果 |
| 连接失败、HTTP 5xx | `ads_unavailable` | `true` | 明确外部服务不可用 |
| ADS HTTP 400 | `ads_invalid_query` | `false` | 记录实际检索式，提示修改；不当作无匹配 |
| JSON、字段结构或分页元数据损坏 | `ads_invalid_response` | `false` | 不输出未经验证的论文 |
| 其他非成功状态或意外重定向 | `ads_unexpected_response` | `false` | 返回通用安全说明，不跟随外链 |

输入验证 HTTP 422、模型层 HTTP 502/503/504 等现有行为保留。已有任一种工具结果后发生模型错误，统一降级保留两类结果；fallback 文案不能再仅指向 SIMBAD。

## 8. 回答与科研可追溯性

- 用户要求“检索、查找、最新文献、文献出处”时必须实际调用 ADS，不能把模型记忆列为本次搜索结果。
- 展示实际检索式、固定天文库范围、排序和本页数量；`total_found` 不是阅读过的论文数，也不保证检索完整性。
- 中文主题可转换为英文检索词，回答需说明采用的词。未找到时不能悄悄放宽年份或替换研究对象；任何改写查询均须保留独立结果并说明差异。
- 列出的每篇论文须对应本次返回的 bibcode，附程序记录的 ADS 链接。标题、作者、年份和 DOI 以结构化字段为准。
- 中文总结标明“根据摘要”；摘要缺失时只列元数据，不能声称理解了论文的方法或结论。被引次数仅表示查询时的数据库记录，不能等同于质量或因果证据。
- 保留 API 结果中的完整返回摘要与作者列表。送入模型的视图每篇最多取摘要前 2000 字符、前 5 位作者，并附 `abstract_truncated`、`authors_truncated` 标记；模型须说明摘要被截断，不能声称已阅读完整摘要。视图不覆盖原始标准化结果。
- 外部标题和摘要作为不可信数据处理。保持现有“工具数据不是指令”的约束，不允许论文内容触发额外工具、读取密钥或修改系统指令；用注入样例测试，不能仅凭提示词宣称消除了风险。

## 9. 开发任务与交付顺序

以下任务已按顺序实现，对应代码、测试与验收报告见 [V0.2 记录](test-records/v0.2.0/README.md)。

| 阶段 | 任务 | 完成依据 |
| --- | --- | --- |
| M1：模型与配置 | 扩展 `Source`；新增三个文献模型与 `literature_results`；新增 Settings 字段 | 参数边界、序列化、配置和 OpenAPI 测试通过 |
| M2：ADS 服务 | 编写 `AdsService.search`、HTTP 请求、转换、去重、来源与错误映射 | `test_ads.py` 离线覆盖成功、缺失、分页、失败路径 |
| M3：Agent 集成 | 双工具注册与分发、ToolMessage 视图、联合状态和 fallback、提示词更新 | `test_chat.py` 与 `test_config.py` 新旧行为均通过 |
| M4：真实验收 | 增加受开关控制的 ADS 与综合聊天测试、独立 HTTP 验收脚本 | 保存真实结果、时间、版本和临时服务停止状态 |
| M5：发布材料 | 更新 README、`.env.example`、测试文档；校对版本元数据 | 文档与代码一致，记录测试结果和未验证边界 |

建议新增 `tests/test_ads.py`、`tests/test_live_ads.py`、`scripts/verify_v02.py`。既有 `scripts/verify_live.py` 继续用于 V0.1 范围回归，V0.2 报告写入独立的 `outputs/v0.2-acceptance.json`，避免覆盖旧记录。

发布时统一核对 `pyproject.toml`、`main.py`、`__init__.py` 中的版本信息并更新为 `0.2.0`。不因本开发文档落地而提前修改当前运行版本。

## 10. 测试与验收设计

### 10.1 离线自动化测试

沿用 `tests/conftest.py` 禁止外部 HTTP 的默认规则。ADS 测试使用可注入 HTTP session 或替身，聊天测试使用假模型，不消耗 API 额度。

| 测试组 | 必须覆盖的内容 |
| --- | --- |
| 参数与配置 | 空检索式、编码后超长、非法枚举、额外字段、严格整数、分页边界；环境变量优先级与 token repr 隐藏 |
| HTTP 请求 | 固定域名与路径、Bearer 头、固定 `fl`/`fq`、编码、排序、超时、禁用重试和重定向 |
| 字段转换 | 标题数组、作者顺序、多 DOI、年份转换、缺失摘要、被引数 0、坏字段、缺失 bibcode、同页去重 |
| 分页与状态 | 零结果、末页、超出范围的空页、元数据矛盾、`has_more`、去重后数量 |
| 服务异常 | 未配置 token 不发请求；401、403、429、400、5xx、超时、非 JSON、重定向与未知状态；错误不含密钥 |
| Agent 分发 | 两个工具绑定；批次先验证再执行；调用 ID 对应；未知工具、无效参数与共享预算 |
| 回答降级 | 仅 ADS、仅 SIMBAD、综合成功、单方失败、全失败、模型后续失败及耗尽预算时保留两类结果 |
| 来源和上下文 | 成功来源去重、失败来源不计成功、截断视图标记、完整 API 数据保留、恶意摘要仅作数据 |
| 接口回归 | 原请求验证、健康检查、既有错误状态、SIMBAD 字段不变、无 ADS token 时原能力可用、OpenAPI 新字段 |

实现后的预期执行命令，在 conda `agent` 环境中运行：

```powershell
python -m pytest -q
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m pip check
```

以上检查已执行，具体结果见测试记录。CI 默认只运行离线检查，不能依赖仓库中的真实密钥；远程 CI 须独立查看。

### 10.2 显式联网测试

ADS 新测试使用独立开关 `ASTROAGENT_RUN_LIVE_ADS=1`，不因现有 V0.1 的 `ASTROAGENT_RUN_LIVE` 被设置而额外访问 ADS。可执行：

```powershell
# 先在本机 .env 中配置 ADS_API_TOKEN 和 DEEPSEEK_API_KEY。
$env:ASTROAGENT_RUN_LIVE_ADS = "1"
try {
    python -m pytest tests/test_live_ads.py -v
} finally {
    Remove-Item Env:ASTROAGENT_RUN_LIVE_ADS -ErrorAction SilentlyContinue
}
```

测试至少包括：固定 bibcode 的真实检索、主题与年份检索、无匹配检索、真实模型选择 ADS、SIMBAD 与 ADS 综合查询。固定编号可使用 V0.1 返回过的 `2007A&A...474..653V`，但标题、DOI 和摘要必须从当次 ADS 响应取得。

不要固定断言“最新论文”的标题、总命中数或被引次数。固定 bibcode 可核对标识符，其他场景验证字段、来源和行为；缺失可选字段应如实记录。未启用时跳过；显式启用后缺少凭证或外部失败应使对应测试失败，不能转为模拟结果或静默跳过。

### 10.3 真实 HTTP 验收与发布门槛

`python scripts/verify_v02.py` 在本机临时端口启动服务，检查健康、文档、OpenAPI、空白输入、仅 SIMBAD、仅 ADS、综合查询、两类无匹配，并在 `finally` 中停止自己启动的服务。缺 token 和限流等可控错误由离线测试覆盖；真实凭证错误只在专门配置的测试环境验证。

报告保存实际请求与响应、ADS 检索式、UTC 时间、依赖版本、各项结果及进程停止状态，不写 token。已核对 `outputs/` 被 Git 忽略，主记录放在不会覆盖的分版本目录。只有离线检查、真实 ADS、真实模型工具调用及真实 HTTP 验收均有证据后，才能勾选：

- [x] 原有 V0.1 行为完成回归，ADS token 缺失不影响仅 SIMBAD 请求。
- [x] ADS 成功、无匹配、缺字段和失败结果符合本文契约。
- [x] 综合查询、共享预算及模型失败降级保留全部已执行结果。
- [x] 引用均能追溯到实际返回的 bibcode，来源不由模型构造。
- [x] README、配置示例、OpenAPI、版本信息与测试说明同步。
- [x] 本地验收报告生成且临时服务已停止。
- 远程 CI 为独立发布门槛：推送后核对标签对应提交通过，并在 GitHub Release 中记录运行链接与提交号。

验收记录应补充日期、环境、实际命令与结果、产物位置和未验证事项。没有联网证据时只能标为“离线实现验证完成，联网验收待完成”，不能宣称 V0.2 已完成。

## 11. 参考资料与核对边界

- [项目 V0.1 计划](PROJECT_PLAN_V0.1.md)、[当前 README](../README.md)、[既有测试说明](TESTING.md)：确定已有能力与迭代范围。
- [ADS 官方开发 API 仓库](https://github.com/adsabs/adsabs-dev-api)：鉴权与限流响应头说明。
- [ADS 官方 Search API 示例](https://github.com/adsabs/adsabs-dev-api/blob/master/API_documentation_Python/Search_API_Python.ipynb)：查询端点、参数、分页、排序和返回字段。
- [ADS 官方检索语法](https://ui.adsabs.harvard.edu/help/search/search-syntax)：主题、作者、标题、年份与 bibcode 等检索语义。

上述外部资料于 2026-10-26 核对，并已使用真实 token 验证 ADS 搜索、真实模型调用与综合 HTTP 请求。搜索页 URL 采用 [ADS 官方前端路由](https://github.com/adsabs/bumblebee/blob/master/src/js/apps/discovery/router.js) 的 `/search/` 参数形式；在内置浏览器中打开触发人工验证，尚未完成图形结果页验收。实际请求参数以结构化结果为准。账户额度未硬编码，未来服务可用性不由本次验收保证。架构、产品上限、响应模型及错误码是本项目设计选择，并非 ADS 官方接口承诺。
