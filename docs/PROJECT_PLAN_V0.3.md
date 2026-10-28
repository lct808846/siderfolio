# AstroAgent 开发文档 V0.3：Gaia 数据查询与分析

**文档日期：** 2026-10-28  
**文档状态：** 已实现，离线与 Gaia 专项通过；SIMBAD 相关联网验收待恢复  
**前置版本：** V0.2.0，SIMBAD 天体查询与 ADS 文献检索  
**本次目标：** 在现有单次、无状态 Agent 中加入有界的 Gaia DR3 查询与程序计算的基础统计，返回可复查的星表数据、单位、查询条件和分析限制。

本文沿用 [V0.1 路线图](PROJECT_PLAN_V0.1.md) 中“V0.3：Gaia 数据查询与分析”的方向，并衔接 [V0.2 开发契约](PROJECT_PLAN_V0.2.md)。初稿编写时版本为 `0.2.0`；2026-10-28 已按下述契约完成代码、模型、工具、测试及脚本，包和应用版本同步为 `0.3.0`。下文保留设计规则与规划阶段对照，实际验收以 [V0.3 测试记录](test-records/v0.3.0/README.md) 为准；不能把已实现误称为全部联网验收通过或已发布。

## 1. 版本范围

### 1.1 必须实现

- 保留现有 `query_simbad`、`search_ads`、接口路径、请求格式和失败降级能力。
- 新增 `query_gaia`：按 Gaia DR3 `source_id` 精确查询，或按 ICRS 坐标作小范围圆锥检索。
- 固定访问 `gaiadr3.gaia_source`，返回位置、参考历元、视差、自行、测光、径向速度及必要的误差和质量字段；缺失值保留为空。
- 支持明确的质量筛选，保留实际执行的 ADQL、筛选条件、返回上限与截断信息。
- 对实际返回样本进行基础统计；仅在满足条件时提供明确标注的视差倒数近似距离。
- 支持 SIMBAD → Gaia 的候选源查找，以及 SIMBAD、ADS、Gaia 联合查询；分别记录每次调用与来源。
- 提供离线测试、独立启用的联网测试和真实 HTTP 验收方案，回归 V0.1 / V0.2。

### 1.2 本版不包含

任意 ADQL / SQL 执行、用户自选表或服务地址、全星表下载、异步 TAP 作业、文件上传交叉匹配、自动翻页、跨请求记忆、前端、用户系统、MCP、RAG、向量数据库、生产部署及多 Agent 编排。

不包含光谱和时序下载、天体物理参数反演、自动零点校正、贝叶斯距离估计、消光校正、星团成员判定、轨道积分或 N-body 分析。本版不生成图表或导出文件；分析以结构化数值和中文解释交付。星团周边检索所得是视场样本，不能直接称为成员星或用于断言星团距离、年龄、质量。

## 2. 使用场景与预期行为

| 场景 | 用户输入示例 | 预期行为 |
| --- | --- | --- |
| 指定源 | 查询 Gaia DR3 source_id 为 5853498713190525696 的视差和自行 | 精确匹配该 DR3 编号，返回实际值、误差、单位与来源；无记录则说明无匹配 |
| 坐标检索 | 以 ICRS 赤经 56.75 度、赤纬 24.12 度为中心，查找 5 角分内最近的 20 个 Gaia DR3 源 | 执行圆锥查询，按角距离排序，说明是否截断及历元限制 |
| 指定质量 | 同一视场只保留 RUWE ≤ 1.4、正视差信噪比 ≥ 10 的源 | 明确加入两项筛选并记录；解释阈值是用户选择，不能保证样本无污染 |
| 名称衔接 | 查询 M45 中心附近 5 角分的 Gaia 数据并总结自行 | 先调用 SIMBAD 取坐标，再查 Gaia；标注位置检索与参考历元不确定性，不认定成员 |
| 距离近似 | 对查询返回的源估算距离，并说明适用条件 | 由程序按第 7 节规则计算；不满足条件的源保留跳过原因 |
| 综合查询 | 查询一个指定 DR3 源的测量信息，并检索相关研究论文 | 分别调用 Gaia 与 ADS，说明文献关联依据；不凭空间接近断言论文研究了该源 |
| 信息不足 | 帮我查这个星团的 Gaia 数据 | 缺少可解析名称或中心与半径时请求补充；下一请求须包含完整条件 |

上表编号、坐标与阈值仅用于说明设计输入，不是本次取得的查询结果或固定验收真值。用户只给坐标而未给历元时，可按输入位置直接查询，但必须标注“输入历元未提供，未进行自行传播”。

## 3. 架构与改动位置（V0.2 → V0.3 对照）

| 位置 | 当前 V0.2 行为 | V0.3 计划改动 |
| --- | --- | --- |
| `src/astroagent/gaia.py` | 不存在 | 新增固定 ADQL 构建、HTTP 请求、VOTable 验证与字段转换 |
| `src/astroagent/analysis.py` | 不存在 | 新增可独立测试的样本统计与距离近似函数，不访问网络或模型 |
| `src/astroagent/schemas.py` | 天体、文献与双来源模型 | 新增 Gaia 参数、源数据、派生量、检索与统计模型；新增响应字段和来源枚举 |
| `src/astroagent/agent.py` | 两个工具；按文献类型区分结果 | 注册第三工具；改为按具体结果类型分流，更新来源聚合、模型视图及降级提示 |
| `src/astroagent/config.py` | 模型、SIMBAD、ADS 与公共预算 | 新增 Gaia 超时；保留现有配置语义 |
| `src/astroagent/api/chat.py` | 每次请求注入 SIMBAD 与 ADS | 注入 Gaia 服务并更新接口描述 |
| `tests/` | SIMBAD、ADS、模型与接口测试 | 新增 Gaia 服务、统计、聊天集成及独立联网测试 |
| `scripts/` 与文档 | V0.1 / V0.2 验收及分版本记录 | 扩展测试入口，新增 V0.3 HTTP 验收与文档，保留旧记录 |

继续使用同步聊天路由在线程池执行、顺序执行工具和有界 Tool Calling 循环，不引入任务队列或新编排框架。新增服务仅在工具执行时访问网络；构造 Agent、健康检查和生成 OpenAPI 不得触发 Gaia 请求。

## 4. 数据源、请求与配置

### 4.1 固定数据发布版

本版固定 `gaiadr3.gaia_source`，响应记录 `release="Gaia DR3"` 和完整表名。这个固定选择用于复现，不宣称 DR3 是运行时最新发布版，不自动改成未来数据表。

字段和单位以 [ESA DR3 数据模型](https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html) 为依据。`source_id` 必须与发布版一起解释；不能直接将 DR2 编号当成 DR3 编号，跨版本对应关系参考 [ESA 的 DR2–DR3 交叉匹配说明](https://gea.esac.esa.int/archive/documentation/GDR3//Catalogue_consolidation/chap_cu9dr2xm/sec_cu9dr2xm_motivation/)。

### 4.2 访问方式

计划使用现有 `requests`，向固定端点 `https://gea.esac.esa.int/tap-server/tap/sync` 提交表单 POST：

| 参数 | 值 |
| --- | --- |
| `REQUEST` | `doQuery` |
| `LANG` | `ADQL` |
| `FORMAT` | `votable` |
| `QUERY` | 由程序模板与验证后的参数构建 |
| `MAXREC` | 圆锥查询为 `limit + 1`；指定源查询为 `2` |

TAP 服务地址参考 [astroquery 官方 TAP 文档](https://astroquery.readthedocs.io/en/latest/utils/tap.html)；同步请求和 VOTable 状态语义参考 [IVOA TAP 1.1](https://www.ivoa.net/documents/TAP/20190927/REC-TAP-1.1.pdf)。小规模同步查询的用途参考 [astroquery Gaia 文档](https://astroquery.readthedocs.io/en/latest/gaia/gaia.html)。本项目的数量限制独立于服务端额度。

公共表查询不引入 Gaia 账号或 token。每次查询使用独立 session，关闭自动重试和重定向，保持 TLS 校验；若端点要求重定向，先记为非预期响应，须核对官方行为后调整契约。使用流式读取，解压后的响应体最多 2 MiB，超限即终止并关闭响应。不允许 XML 外部实体、外部文件或远程 VOTable 数据引用。

用 `astropy.io.votable` 解析内存中的结果；直接导入 Astropy 时须在 `pyproject.toml` 显式声明兼容依赖并验证安装，不能依赖 astroquery 的传递依赖。保留 astroquery 供现有 SIMBAD 使用。本方案避免 Gaia 客户端隐式初始化、元数据获取或异步轮询；全部网络请求必须能在离线测试中拦截。

### 4.3 配置与资源边界

| 变量 | 默认值 | 规则 |
| --- | --- | --- |
| `GAIA_TIMEOUT_SECONDS` | `20` | 浮点数，`0 < value <= 120`；分别作为连接和读取超时 |
| `AGENT_MAX_ROUNDS` | 沿用 `4` | 三种工具共用现有模型轮数预算 |
| `AGENT_MAX_TOOL_CALLS` | 沿用 `6` | SIMBAD、ADS、Gaia 的调用合计，不另开隐藏预算 |

连接/读取超时不是整个聊天请求的总时限，持续分块响应也不具有严格总耗时保证。本版不承诺服务 SLA。查询半径、条数和响应体上限用于限制工作量；后续若引入严格总时限，须单独设计取消机制与测试。

缺少 `ADS_API_TOKEN` 不影响只查询 Gaia；聊天仍需要模型密钥。非法 Gaia 超时按现有 Settings 规则返回 `invalid_configuration`，健康检查保持仅验证服务可响应。`.env.example` 中新增超时示例，不增加服务 URL、表名或任意 ADQL 配置。

## 5. `query_gaia` 工具与查询规则

### 5.1 输入模型

新增 `GaiaQuery`，使用 `extra="forbid"`、字符串首尾清理及跨字段验证。工具仅接受以下字段：

| 参数 | 类型 / 默认值 | 规则 |
| --- | --- | --- |
| `mode` | `source_id` 或 `cone`，必填 | 决定互斥的两种查询方式 |
| `source_id` | 字符串，可空 | 指定源模式必填；仅 ASCII 正整数字符串，无前导零，数值不超过有符号 64 位整数上限 |
| `ra_deg` | 数值，可空 | 圆锥模式必填，`0 <= value < 360` |
| `dec_deg` | 数值，可空 | 圆锥模式必填，`-90 <= value <= 90` |
| `radius_arcmin` | 数值，可空 | 圆锥模式必填，`0 < value <= 30` |
| `limit` | 严格整数，`20` | 圆锥模式为 1–100；指定源模式拒绝显式提供 |
| `ruwe_max` | 数值，`null` | 圆锥模式可选，`0 < value <= 10` |
| `parallax_snr_min` | 数值，`null` | 圆锥模式可选，`0 < value <= 1000`，仅选择正视差和正误差 |
| `estimate_distance` | 严格布尔值，`false` | 是否执行第 7 节的逐源近似距离计算 |

指定源模式拒绝所有圆锥字段和质量筛选；圆锥模式拒绝 `source_id`。数值不接受布尔值、字符串、NaN 或无穷值；坐标可接受有限整数或浮点数。`source_id` 从输入到 JSON 输出始终保留为字符串，不能经过浮点数转换，避免大整数精度损失。

工具参数示例（设计输入，未执行）：

```json
{
  "mode": "source_id",
  "source_id": "5853498713190525696",
  "estimate_distance": true
}
```

```json
{
  "mode": "cone",
  "ra_deg": 56.75,
  "dec_deg": 24.12,
  "radius_arcmin": 5.0,
  "limit": 20,
  "ruwe_max": 1.4,
  "parallax_snr_min": 10.0,
  "estimate_distance": false
}
```

### 5.2 ADQL 构建

字段、表名、函数和排序均为程序常量；用户和模型不提供查询片段。数值经验证后用统一的有限数值格式写入模板。弧分除以 60 转为度。圆锥查询示意如下，`<固定字段>` 在实现中替换为第 6 节完整列清单：

```sql
SELECT TOP 21 <固定字段>,
  DISTANCE(POINT('ICRS', ra, dec), POINT('ICRS', 56.75, 24.12)) AS separation_deg
FROM gaiadr3.gaia_source
WHERE 1 = CONTAINS(
  POINT('ICRS', ra, dec), CIRCLE('ICRS', 56.75, 24.12, 0.08333333333333333)
)
  AND ruwe <= 1.4
  AND parallax > 0
  AND parallax_error > 0
  AND parallax / parallax_error >= 10
ORDER BY separation_deg ASC, source_id ASC
```

没有显式质量筛选时不添加相应条件。指定源模板使用 `SELECT TOP 2 ... WHERE source_id = <已验证整数>`，不计算角距离。不得使用 `SELECT *`、任意联表、远程表、用户函数或额外计数查询。

### 5.3 数量与截断

圆锥请求取 `limit + 1` 行，以多取一行判断是否还有匹配；仅返回前 `limit` 行，哨兵行不进入统计或模型上下文。按距离和编号稳定排序，不自动翻页，不提供 `start` 参数。`total_found=null`，不把已返回数量当作总命中数。

须检查 VOTable 结果资源中表前和表后的全部 `QUERY_STATUS`。`ERROR` 即使伴随 HTTP 200 也作为失败；`OVERFLOW` 明确记录为 `archive_overflow=true`，`has_more=true`，标注服务器截断。合法且完整的零行结果才是 `not_found`；零行但带 `OVERFLOW` 或缺失状态/表结构时按异常响应处理。

正常完整响应有哨兵行时 `has_more=true`，否则为 `false`。`truncated` 在出现哨兵行或服务端溢出时为真。若实际表行数超过请求上限、同一 `source_id` 重复，或指定源模式返回多行/不同编号，整次结果标为异常，不静默去重掩盖问题。

### 5.4 名称与位置匹配

`query_gaia` 不接受名称，也不在服务层隐藏执行 SIMBAD。用户给名称时，Agent 先单独执行 `query_simbad`，再将实际返回坐标作为圆锥中心；两次都计入工具预算。SIMBAD 失败或缺少坐标时停止该链路；不能用模型记忆补坐标。

Gaia 位置和自行须保留返回的 `ref_epoch`，DR3 的参考历元通常为 J2016.0；解释应结合 [Gaia 天体测量论文](https://arxiv.org/abs/2012.03380)。现有 SIMBAD 响应只给 ICRS，不给可用于传播的历元与自行，因此本版不做自动历元换算。ICRS 坐标系相同不代表参考历元相同。

圆锥结果一律称“位置候选源”。最近的一行不能自动认定为名称对应源，只有一行也不代表确认匹配。响应警告说明未作自行传播、拥挤视场或高自行源可能漏配。用户明确给 DR2 编号、其他坐标系或要求精确跨历元匹配时，说明本版限制并请求 DR3 编号 / 合适坐标，不静默转换或放大半径。

## 6. 数据模型与来源

### 6.1 `GaiaSourceData` 固定字段

| 返回字段 | 单位 / 含义 |
| --- | --- |
| `source_id` | 字符串，Gaia DR3 编号，必填 |
| `ra`, `dec` | 度，ICRS 位置，必填 |
| `ref_epoch` | Julian year，参考历元，必填 |
| `ra_error`, `dec_error` | mas，目录给出的天体测量位置误差 |
| `parallax`, `parallax_error` | mas，视差及误差，负视差保留 |
| `pmra`, `pmra_error`, `pmdec`, `pmdec_error` | mas/yr，自行分量及误差 |
| `phot_g_mean_mag`, `phot_bp_mean_mag`, `phot_rp_mean_mag`, `bp_rp` | mag，目录测光和颜色 |
| `radial_velocity`, `radial_velocity_error` | km/s，径向速度及误差 |
| `ruwe` | 无量纲，天体测量拟合质量指标 |
| `astrometric_params_solved` | 整数，目录天体测量解类型编码 |
| `duplicated_source` | 布尔值，目录标志，不是本查询返回重复行的标志 |
| `separation_arcsec` | 程序将圆锥查询的角距离从度转为角秒；指定源模式为 `null` |

`pmra` 已含赤纬余弦因子，不能再乘一次。单位与字段含义以 [Gaia 源表说明](https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html) 核对。原始列名尽量保留，避免单位不明的 `distance` 或 `brightness` 字段。

转换规则：可选列的掩码或非有限测量值转为 `null`；必填列缺失、类型错误、无效坐标或非有限历元使整次结果失败。有效误差非负，负误差与错误的字段类型视为坏响应，不能用零替代。`source_id` 用整数或十进制字符串路径解析。未知附加列不对外暴露，不将服务端字符串解释为指令。

### 6.2 `GaiaQueryResult`

| 字段 | 计划含义 |
| --- | --- |
| `query` | 验证后生效的工具参数，包括默认值；指定源模式不含无关圆锥字段 |
| `release`, `table`, `endpoint` | 固定发布版、数据表与实际请求端点 |
| `adql`, `maxrec` | 完整实际查询与传输条数上限 |
| `status` | `success` / `not_found` / `error` |
| `returned_count` | 实际交付行数；失败为 0 |
| `total_found` | 本版恒为 `null`，未执行总数查询 |
| `has_more` | 布尔值；失败时为 `null` |
| `truncated`, `archive_overflow` | 本地上限与服务端截断信息；失败时为 `null` |
| `data` | `list[GaiaSourceData]`；失败或无匹配时为空 |
| `analysis` | 第 7 节计算结果；无匹配或失败时为 `null` |
| `source` | `name="Gaia"`、官方 Archive 入口 URL 与 UTC 请求记录时间 |
| `warnings`, `error` | 本次质量/位置/分析限制，或安全的 `ErrorInfo` |

`Source.name` 在现有 `SIMBAD`、`ADS` 上增加 `Gaia`。`source.url` 固定为 `https://gea.esac.esa.int/archive/`，复查条件由 `adql` 与 `endpoint` 提供；不虚构单源详情页或声称链接会自动执行检索。每次调用保留自己的来源时间，顶层来源按 URL 去重并保留首次成功记录；多个 Gaia 查询可共享一个顶层入口。

`ChatResponse` 新增默认空列表 `gaia_results`。`results` 继续只含 SIMBAD，`literature_results` 继续只含 ADS；顶层 `sources` 只聚合成功数据库结果，失败和无匹配尝试留在各次记录。此次新增字段及枚举可能影响严格客户端，升级说明须明确提示。

## 7. 基础分析与科学解释

新增 `GaiaAnalysis`，由纯 Python / NumPy 函数计算，不由模型心算，不额外访问数据库。成功查询默认统计本次实际交付的全部行；即使模型只看到部分行，统计也不能改用模型样本。

### 7.1 样本统计

- `sample_size` 等于 `returned_count`，记录 `scope="returned_rows"`、是否截断及实际质量筛选。
- 对 `parallax`、`pmra`、`pmdec`、`phot_g_mean_mag`、`bp_rp`、`radial_velocity` 分别返回 `valid_count`、`missing_count`、中位数、最小值、最大值与单位；无有效值时三个统计量均为 `null`。
- 记录负视差数、零视差数和缺失视差数；不在未请求筛选时删除这些行。
- 不平均赤经或自行角度，不以所取视场的统计量代表星团或总体。样本只有一行时仍可返回描述统计，但不暗示总体推断。

RUWE ≤ 1.4 和正视差信噪比 ≥ 10 都是可选产品筛选，不默认打开，也不是 Gaia 官方保证的“可靠恒星”判据。阈值会改变选择函数；必须区分“未查询到”与“被筛选排除”，但没有额外计数证据时不能给出排除数量。

### 7.2 近似距离

仅当 `estimate_distance=true` 时计算逐源 `distance_estimates`，每项以 `source_id` 对应原始行。要求视差与误差有限、视差 > 0、误差 > 0、`parallax / parallax_error >= 10`；否则距离和误差均为 `null`，记录 `missing_parallax`、`non_positive_parallax`、`invalid_or_missing_error` 或 `low_parallax_snr`，按此顺序判定首个失败原因。

满足条件时采用以下一阶近似，视差和误差均以 mas 输入：

```text
distance_pc = 1000 / parallax
distance_error_pc = 1000 * parallax_error / parallax**2
method = "inverse_parallax_high_snr"
zero_point_corrected = false
```

例如合成测试值 `parallax=10 mas`、`parallax_error=0.5 mas` 应得到 `100 pc` 与一阶随机误差 `5 pc`。这不是观测记录，也不是可靠性证明。阈值 10 是本项目的保守展示规则，不能消除系统误差、样本选择偏差或先验影响。

倒数视差对低信噪比源并不适合，参考 [Bailer-Jones 距离目录与方法说明](https://bailer-jones.www3.mpia.de/gedr3_distances.html)。Gaia 视差具有随星等、颜色和位置等变化的零点偏差，参考 [Lindegren 等的原始研究](https://arxiv.org/abs/2012.01742)。本版不使用统一常数修正，不把近似值称为 Gaia 直接测得的距离，不报告贝叶斯置信区间或未处理的系统误差。

`estimate_distance=false` 时 `distance_estimates=[]`，不生成距离。该开关和所有被跳过的原因必须进入分析记录；模型不得对跳过行另行计算或补写距离。

## 8. Agent 集成与错误降级

### 8.1 工具执行和模型上下文

1. 在现有工具 schema 注册表加入 `query_gaia`，继续先验证整个工具批次，再逐次执行。未知工具、重复调用 ID 和无效参数沿用 `model_invalid_tool_call` 行为。
2. 使用统一的有序结果列表保留三类实际调用；按具体类型显式分入三个响应列表。现有“非文献即 SIMBAD”的判断必须替换，包括 `_response`、来源聚合与 `_fallback`。
3. 模型视图最多展示前 10 行，并提供 `rows_shown_to_model`、`rows_omitted_from_model`、完整样本统计、查询条件和所有警告；距离近似只展示这些行对应的条目及全样本计算/跳过数量。API 保留全部至多 100 行及其分析。
4. 回答列出发布版、查询方式、中心/半径或编号、单位、质量筛选、交付数量和截断情况；区分目录原始值、程序派生量与模型解释。
5. 更新系统提示词中“亮度、距离等尚未查询”的描述，按具体工具能力说明；不能让旧提示否认 Gaia 实际返回字段，也不能允许模型补写未返回的测量。

一次名称 → Gaia → 文献 → 总结通常需要四次模型调用，受现有默认轮数限制；可在同批执行独立工具，但不得为此突破预算。触顶时保留全部已执行结果并明确未完成步骤，不能宣称整个问题已完成。

### 8.2 错误码

| 情况 | 结果 / 错误码 | `retryable` |
| --- | --- | --- |
| 完整合法响应零行 | `not_found` / `gaia_not_found` | `false` |
| 连接或读取超时 | `error` / `gaia_timeout` | `true` |
| HTTP 429 | `error` / `gaia_rate_limited` | `true` |
| 连接失败或 HTTP 5xx | `error` / `gaia_unavailable` | `true` |
| HTTP 401 / 403 | `error` / `gaia_access_denied` | `false` |
| HTTP 400 或 TAP `QUERY_STATUS=ERROR` | `error` / `gaia_query_failed` | `false` |
| 响应体超限 | `error` / `gaia_response_too_large` | `false` |
| 重定向、坏 XML、坏类型、缺必要列、异常行数或其他意外响应 | `error` / `gaia_unexpected_response` | `false` |

固定模板被服务拒绝时应检查实现或接口变化，不能把原始服务端异常直接推给用户，也不能把 ADQL 错误误报成无匹配。外部错误只输出经过清理的中文说明，日志不记录密钥、请求认证头或未经审查的原始异常。

数据库层失败与现有行为一致：HTTP 200，逐次结果保留错误；无成功数据则顶层 `error`，部分工具成功则 `partial`。成功 Gaia 查询即使含截断或距离跳过，也可保持 `success`，由条目警告解释限制。已有数据后模型失败或调用触顶则保留三类结果并返回顶层 `warnings`；成功数据存在时为 `partial`。无工具结果前的模型失败沿用现有 502 / 503 / 504。

## 9. 测试设计

### 9.1 离线测试

保持默认禁止外部 HTTP，不需要 API 密钥。新增测试应覆盖真实契约与失败模式：

| 测试组 | 关键断言 |
| --- | --- |
| 参数与模板 | 两种模式互斥、严格类型、有限数值、坐标/半径边界、64 位编号字符串、注入片段被拒绝；固定表名/列/排序，角分正确转换 |
| HTTP 行为 | 固定同步端点、POST 表单、MAXREC 与 TOP 一致、无自动重试或重定向、连接/读取超时、流式响应超限会关闭连接 |
| VOTable 与数据 | 表前/表后 ERROR、OVERFLOW、空表、坏 XML、缺列、掩码、非有限值、负误差、重复编号、64 位编号无精度损失、单位和布尔/整数转换 |
| 截断语义 | 0 / 少于 / 等于 / 多于 limit、服务溢出、零行溢出；哨兵行排除在数据和统计外，total_found 始终未知 |
| 分析 | 合成值的统计量、全缺失列、单行样本、负/零视差、误差缺失、SNR=10 边界、100 pc / 5 pc 示例、开关关闭不产生距离 |
| Agent 与接口 | 三工具选择与顺序、失败混合、全部失败、结果准确分流、来源去重、上下文只显示前 10 行但完整统计/API 不丢数据 |
| 预算与隔离 | 批量参数先校验、名称解析不隐藏调用、所有工具共享上限、后续模型失败保留 Gaia 数据、健康检查/建模不触网 |
| 科学解释 | 候选源不当作确认匹配，未校正历元/视差零点有提示，统计范围和距离方法明确，工具内嵌指令不能改变工具协议 |

已有 SIMBAD 首次元数据请求的超时回归测试必须保留；不能因为加入第三服务重新引入无界初始化。模拟模型测试验证提示与结构化协议，不能替代真实模型的科学解释验收。

### 9.2 显式联网测试（已新增）

新增 `tests/test_live_gaia.py` 和独立开关 `ASTROAGENT_RUN_LIVE_GAIA=1`。现有 `ASTROAGENT_RUN_LIVE`、`ASTROAGENT_RUN_LIVE_ADS` 不启用 Gaia；未开启时跳过，显式开启后服务失败或缺少该测试所需密钥必须失败，不能改成跳过。

- 直接 Gaia 精确编号与小圆锥测试：核对编号字符串、坐标范围、单位、历元、结果边界和查询记录，无需模型密钥。
- 真实模型调用 Gaia、名称 → SIMBAD → Gaia、三工具综合请求：按测试要求检查 DeepSeek / ADS 配置，实际执行并保存结构化结果。
- 无匹配场景先通过有界真实查询确认测试条件，避免把一个可能存在的编号或视场永久写死为“无结果”。
- 不以精确测量数值或固定命中总数作长期断言；记录实际值和环境，不能用硬编码数据替代外部失败。

### 9.3 HTTP 验收与记录（已新增）

新增 `scripts/verify_v03.py`，实际启动临时本机 Uvicorn 服务，验证 `/health`、`/docs`、`/openapi.json`、空输入、Gaia 两种模式、无匹配、质量筛选、分析开关、SIMBAD 回归、ADS 回归和三工具综合请求。失败降级由离线故障注入覆盖；实测遇到的外部失败如实保留，不修改报告冒充成功。`finally` 停止自己启动的进程并记录停止状态。

已扩展 `scripts/run_tests.py --live-gaia`，显式控制三种联网开关；离线分支将三者都设为 `0`，避免继承环境变量使默认测试意外联网。以下命令现可执行，显式联网失败会保存为失败：

```powershell
python scripts/run_tests.py --live-gaia
python scripts/verify_v03.py
```

当前可用的离线检查入口为 `python scripts/run_tests.py`。V0.3 实现阶段的记录保存到 `docs/test-records/v0.3.0/<类型>/<UTC运行时间>/`，建议类型为 `offline-tests`、`live-gaia-tests`、`acceptance-v03`；现有其他联网记录也按实际运行版本保存。每次新建目录，不覆盖失败报告或旧版本记录。

归档器默认读取 `pyproject.toml` 版本；开发阶段已同步包和应用版本，并保留 Git 提交号及工作区是否有未提交改动。报告记录命令、依赖、UTC 时间、真实输入/响应、实际 ADQL、检查结果和服务停止证据。离线结果不能代替联网验收。

## 10. 开发顺序与验收清单

| 里程碑 | 交付物 | 完成条件 |
| --- | --- | --- |
| M1：参数与接口模型 | Gaia 模型、配置和契约测试 | 类型、边界、互斥、单位和兼容性要求确定，旧接口测试通过 |
| M2：Gaia 服务 | 固定 ADQL、同步 HTTP、VOTable 转换与错误映射 | 全部服务离线测试通过，直接公共查询联网验证通过 |
| M3：基础分析 | 样本统计与可选距离近似 | 合成数据和边界测试通过，派生结果能追溯到实际行 |
| M4：Agent 集成 | 三工具注册、结果分流、上下文与降级 | 新旧离线测试通过，真实模型调用与科学限制检查通过 |
| M5：版本验收 | README、配置、测试说明、升级说明与归档报告 | HTTP 验收通过、服务停止证据完整，遗留限制明确 |

2026-10-28 实现状态：M1 / M2 / M3 已通过离线与 Gaia 公共查询验证；M4 的离线集成与真实模型精确源查询通过，名称链路 / 三工具成功路径受 SIMBAD 超时阻塞；M5 文档与脚本完成，HTTP 实测 9/12 通过，进程与端口关闭已确认。完整联网验收仍未满足原门槛；本次发布调整见下述明确授权，失败状态保持不变。

- [x] V0.1 / V0.2 离线功能和错误契约回归通过，三类结果互不混入。
- [x] 精确源与圆锥查询使用真实固定 Gaia DR3 表，并保留可复查 ADQL。
- [x] 编号精度、误差、单位、历元、缺失值和截断规则均有测试。
- [x] 统计只代表实际返回样本，距离近似按条件执行并保留跳过原因。
- [x] 名称解析依赖、位置候选歧义与未做的科学校正在结构化警告和提示中明确展示。
- [x] 共享预算、网络资源边界、失败降级和模型上下文上限已离线验证。
- [x] 默认离线测试、Ruff 检查/格式、依赖检查通过。
- [ ] 显式 Gaia / 原有联网测试与真实 HTTP 验收通过，失败历史保留。
- [x] OpenAPI、版本、README、环境变量和测试入口同步，报告明确记录未提交开发状态。

代码已实现，但不把外部失败改写为成功。原发布要求为全部真实服务验收与远程 CI 通过；2026-10-28 用户明确要求在保留当日 SIMBAD 连接失败记录的情况下直接发布。该授权仅豁免本次外部连接限制，离线检查及目标提交的主分支/标签 CI 仍需通过，CI、标签和发布提交须一致。按既有方式提供源码发布，不打包安装器；SIMBAD 恢复后仍需补验完整成功路径。

实现细化：ESA 实测返回 BINARY2，计算别名 `separation_deg` 不附单位；仅此固定 `DISTANCE(POINT, POINT)` 别名按度处理并转换为角秒，目录测量列仍严格核对单位。使用 Astropy 掩码记录直接转换，支持 FIELD 名称与 ID 不同。另验证 VOTable 行数/数组分配提示，禁止外部数据引用；极端有限数造成距离不可表示时保留 `numerical_overflow` 原因，不输出 Infinity。以上均有离线回归测试。

## 11. 参考资料与核对边界

- [当前 README](../README.md)、[V0.1 计划](PROJECT_PLAN_V0.1.md)、[V0.2 开发文档](PROJECT_PLAN_V0.2.md)、[测试说明](TESTING.md)：当前实现与既有边界。
- [astroquery Gaia 官方文档](https://astroquery.readthedocs.io/en/latest/gaia/gaia.html)：公共表访问、同步查询和 VOTable 示例。
- [astroquery TAP 官方文档](https://astroquery.readthedocs.io/en/latest/utils/tap.html)：ESA TAP 服务地址。
- [IVOA TAP 1.1 推荐标准](https://www.ivoa.net/documents/TAP/20190927/REC-TAP-1.1.pdf)：同步查询参数、VOTable 状态和溢出语义。
- [ESA DR3 源表数据模型](https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html)：字段与单位；实现时须再次用官方表元数据核对。
- [ESA DR2–DR3 交叉匹配说明](https://gea.esac.esa.int/archive/documentation/GDR3//Catalogue_consolidation/chap_cu9dr2xm/sec_cu9dr2xm_motivation/)：发布版编号与匹配限制。
- [Lindegren 等：EDR3 天体测量解](https://arxiv.org/abs/2012.03380)、[视差零点偏差](https://arxiv.org/abs/2012.01742)：参考历元与系统误差。
- [Bailer-Jones 距离目录与方法](https://bailer-jones.www3.mpia.de/gedr3_distances.html)：简单视差倒数的适用限制。

资料于 2026-10-28 查阅。ESA DR3 源表完整页面直连仍返回 503；实现阶段已执行真实 TAP 查询，取得官方字段类型/单位元数据并保存 [原始响应与元数据](test-records/v0.3.0/gaia-metadata/20261028T033820264281Z/report.json)，验证固定模板与字段映射。Gaia 专项、真实模型精确源和 HTTP Gaia 场景通过；含 SIMBAD 的完整成功路径尚未通过联网验收。半径、条数、响应体、质量阈值、模型视图和数据结构属于项目设计，不是 ESA 的服务承诺。
