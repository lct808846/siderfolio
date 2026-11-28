# Siderfolio V2.3 开发文档｜天文数据表分析、交叉匹配与 VizieR 星表集成

**日期** 2026-11-28　**目标版本** `v2.3.0`　**实施基线** `v2.2.1`（`464e249`）　**状态** 已实现，已通过本机改动复验

[本机复验记录](test-records/v2.3.0/acceptance/20261128T085902Z/README.md) · [版本说明](releases/v2.3.0.md)

沿用科研绘图与 N 体模拟的一体化工作台模式（不新增独立页面），在主工作台对话流与右侧核查栏中打通「**多格式天文表导入（FITS / VOTable / ECSV / CSV / TSV）+ Gaia DR3 / VizieR 只读星表检索 → 确定性筛选、坐标变换、天空坐标交叉匹配与误差拟合 → 派生表持久化、直连隔离绘图与可复现导出**」完整链路。所有计算均由后端 `Astropy` / `NumPy` / `SciPy` 确定性执行并保留来源、单位、历元与血缘，严禁模型口算或伪造统计/拟合数值。

---

## 1. 实施基线、硬件边界与发布范围

### 1.1 现有底座复用（零新增运行依赖、零新增容器）

生产后端镜像（[requirements-runtime.lock](../containers/application/requirements-runtime.lock)）已锁定 `astropy==8.0.2`、`astroquery==0.4.11`、`numpy==2.5.4`、`scipy==1.18.1`、`defusedxml==0.7.1`，可直接在现有 FastAPI 后端与 `2 vCPU / 8 GiB` 单机部署上亚秒级运行万行级表格算子，无需新增依赖包或独立计算 Worker。

| 已有能力 | V2.3 增量 |
| --- | --- |
| SIMBAD、NASA ADS、ESA Gaia DR3 查询与本地 `stdio` Astronomy MCP（[gaia.py](../src/astroagent/gaia.py) · [mcp_server.py](../src/astroagent/mcp_server.py)） | 新增 **VizieR 只读星表检索**（TAP/VOTable 严格安全解析、5 个内置常用星表快捷项 + 自定义表 ID），纳入 `astronomy_queries` 小时配额、统一工具目录与本地 MCP |
| 项目隔离绘图与 `plot_datasets`（[plot_data.py](../src/astroagent/plot_data.py) · [plot_service.py](../src/astroagent/plot_service.py)），目前仅支持 UTF-8 CSV/TSV 与 Gaia 快照 | 新增租户私有 schema 增量表管理项目数据表（自动幂等初始化），支持 **FITS / VOTable / ECSV / CSV / TSV / Gaia / VizieR / 派生表**，一键桥接现有隔离 Python/Gnuplot 绘图 |
| 对话附件解析（[attachments.py](../src/astroagent/attachments.py)），目前支持图片、PDF、DOCX、TXT/MD、CSV/TSV、JSON | 扩展支持 `.fits` / `.fit` / `.vot` / `.ecsv` 离线结构解析（向模型仅提供表头/列单位与前若干行摘要，不将原始二进制塞入上下文），支持一键保存到项目数据表 |
| V2.1 统一工具目录与内置 `SKILL.md`（[tool_catalog.py](../src/astroagent/tool_catalog.py)）、V2.2 长期记忆与运行追踪（[memory_store.py](../src/astroagent/memory_store.py)） | 新增内置科研技能 `astronomy-table-analysis`、只读 `list_project_tables` 与需用户确认执行的 `prepare_table_analysis` 方案卡片；RunTrace 同步记录表分析与 VizieR 调用元数据 |

### 1.2 分期范围

| 优先级 | 交付范围 |
| --- | --- |
| **P0 发布门槛** | 1) 租户隔离项目数据表存储（自动幂等建表，计入账号存储配额）；2) FITS Table / VOTable / ECSV / CSV / TSV 安全解析与导出；3) Gaia 轮次/快照一键导入与 **VizieR 只读星表检索**（内置常用星表 + 自定义表 ID）；4) 确定性算子：描述统计与相关/KS 检验、白名单结构化筛选与派生列、ICRS↔银道坐标与角距、天空坐标交叉匹配（最近邻/多候选 + 历元与错配提示）、4 类确定性科学拟合（线性含 WLS / 多项式 / 幂律 / 单高斯）；5) 派生表保存、血缘追踪、一键桥接隔离绘图与 ZIP 复现包；6) 工作台一体化界面（右侧 `ResultPanel` 嵌入 `TableResultPanel`、对话内 `ChatTableAnalysisCard`、VizieR/Gaia 一键存表、项目抽屉入口与 `/tables` 重定向）、内置 `astronomy-table-analysis` Skill |
| **P1 增量（视时间与反馈安排）** | 多表链式交叉匹配（3 表级联）、多高斯/Voigt 谱线拟合、基于 3D 尘埃图或外置表的消光查询接口、批量表对比视图 |
| **明确不做（保持边界）** | 任意用户 Python 代码在后端宿主机执行（严禁 `eval`/`exec`，自定义脚本绘图继续严格走无网隔离绘图容器）；FITS 图像（2D/3D Image HDU）测光与图像处理；大规模星表分布式计算（> 2 万行或 > 10 MiB）；自动判定星团成员或隐式修改视差/消光 |

---

## 2. 界面入口与交互规范

沿用科研绘图（`ChatPlotCard` + `PlotResultPanel`）与 N 体模拟（`ChatNBodyCard` + `ComputeResultPanel`）的**对话驱动 + 右侧结果核查栏一体化模式**，不增设独立页面，也不在右侧栏重复堆叠手动上传、VizieR 检索或手动算子表单：

| 区域 | 主要内容与交互 |
| --- | --- |
| **对话输入与附件自动入表** | 用户直接在对话输入框拖入或上传 `.fits` / `.fit` / `.vot` / `.ecsv` / `.csv` / `.tsv`（发送时自动静默同步为当前空间数据表），或直接以自然语言让助手检索 **VizieR** / **Gaia DR3** 星表 |
| **对话内联卡片（`ChatTableAnalysisCard`）** | 模型调用只读 `list_project_tables` / `query_vizier` 后，通过 `prepare_table_analysis` 生成可审阅参数卡片；用户核对参数并点击「确认执行分析」后由后端 `Astropy`/`NumPy`/`SciPy` 确定性运算，结果同步呈现并支持「送去隔离绘图」与「↓ ZIP 可复现包」 |
| **右侧结果栏（`ResultPanel` → `TableResultPanel`）** | 纯粹作为数据与产物核查器：展示 VizieR / Gaia 查询结果（会话中检索得到的星表结果在触发数据表分析时自动幂等同步，无需手动点击「存入项目数据表」）；切入 `TableResultPanel` 后按「数据预览」「分析记录」查看当前空间数据表、列单位与 64 位 `source_id`、拟合/交叉匹配 KPI、科学边界告警，并支持「送去科研绘图」「↓ CSV / ECSV / FITS」「↓ ZIP 可复现包」与删除 |

其他入口收敛：
- `/tables` 与 `/projects/:projectId/tables` 自动重定向至 `/?result=tables&project=...` 原地唤起右侧栏；
- 左侧项目菜单、项目管理抽屉（`ProjectManageDrawer`）、来源关联页与设置页中的「数据表记录」入口均原地唤起右侧 `TableResultPanel`；
- 空白新会话时右侧栏保持干净的「暂无文件与产物」，不展示多余的独立入口按钮。

UI 一致性严格遵循 [UI 设计规范](UI_DESIGN_SPEC.md) 与 [AGENTS.md](../AGENTS.md)：
- 全部下拉选择统一使用 `UiSelect`，禁止原生 `<select>`；
- 错误与警告提示统一使用 `StatusNotice` 顶部浮层，禁止在卡片或弹窗内堆叠内联错误盒；
- 禁止在任何页面、卡片或弹窗设置「刷新」按钮，进入页面、打开弹窗、切换表或完成写操作后自动同步；
- 附属导入、删除确认与血缘详情使用居中 `<dialog>`，空状态统一使用扁平无框 `.ui-empty-inline`。

---

## 3. 多格式安全解析与 VizieR 只读查询

### 3.1 天文表解析契约与安全防线

所有上传文件与外部 VOTable 均在受限并发槽（`ANALYSIS_SLOTS = BoundedSemaphore(2)`）内离线解析，超限即拒绝并返回明确中文提示，**不做静默截断**：

| 格式 | 支持后缀 | 解析实现与安全约束 |
| --- | --- | --- |
| **FITS 表格** | `.fits`、`.fit` | 使用 `astropy.io.fits`（`memmap=False`、禁网络、校验头签名 `SIMPLE  =`）；仅读取 `BinTableHDU` / `TableHDU`，拒绝纯图像 HDU 与超限变长数组（VLA）；存在多个表 HDU 时返回 HDU 清单由用户指定，默认选中首个表 HDU；提取列 `TUNIT*`、`TCOMM*` 与关键观测头（`OBJECT`、`EQUINOX`、`RADESYS`、`MJD-OBS`、`DATE-OBS`） |
| **VOTable** | `.vot`、`.xml` | 先以 `defusedxml` 禁止 DTD / 外部实体 / XML 炸弹，再由 `astropy.io.votable.parse()` 解析；保留 `unit`、`ucd`、`description` 与 `COOSYS`（坐标系与历元） |
| **ECSV** | `.ecsv` | `astropy.io.ascii`（`format="ecsv"`），完整保留 YAML 元数据中的单位、dtype、列描述与自定义表元信息 |
| **CSV / TSV** | `.csv`、`.tsv` | 沿用 UTF-8（含 BOM）严格解析，支持明确空值与 64 位整数标识保护 |

统一表边界与数值保真约定：
- **容量上限**：单个上传文件 `<= 10 MiB`；单张表 `1 <= rows <= 20,000`、`1 <= columns <= 64`；规范化表数据（gzip 压缩后存入租户表）受 `<= 8 MiB` 上限与账号 `storage_mib` 总配额双重约束；单项目最多保存 `40` 张数据表与 `120` 条分析记录。
- **宽表处理**：若 FITS/VOTable 列数超过 64，允许在导入预览弹窗勾选不超过 64 个目标列再导入，避免强行丢列或整表不可用。
- **标识符保真**：64 位整数列（如 Gaia `source_id`、`designation`、长度超过 15 位的整数）统一按 `identifier` 精确字符串保存，严禁经 JSON/IEEE-754 双精度浮点转换丢失末位精度。
- **科学边界声明**：所有导入与统计均显式保留「未自动校正星际消光、视差零点或系统误差」「负视差为合法测量值，不默认删除」等提示。

### 3.2 VizieR 只读星表检索（`src/astroagent/vizier.py`）

沿用 [gaia.py](../src/astroagent/gaia.py) 的有界 TAP/VOTable 架构，直连 CDS VizieR TAP 同步端点（`https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync`，默认超时 `30 s`，响应上限 `4 MiB`），每次外部查询扣减 `astronomy_queries` 小时配额：

1. **内置 5 个常用星表预设（固化表名、默认列、单位、坐标列与参考历元）**：
   - `II/246/out`：**2MASS Point Source Catalog (PSC)**（`RAJ2000`、`DEJ2000`、`Jmag`、`e_Jmag`、`Hmag`、`e_Hmag`、`Kmag`、`e_Kmag`、`Qflg`，参考历元 `J2000.0`）
   - `II/328/allwise`：**AllWISE Source Catalog**（`RAJ2000`、`DEJ2000`、`W1mag`、`e_W1mag`、`W2mag`、`e_W2mag`、`W3mag`、`e_W3mag`、`W4mag`、`e_W4mag`、`qph`，参考历元 `J2010.0`）
   - `II/349/ps1`：**Pan-STARRS DR1**（`RAJ2000`、`DEJ2000`、`gmag`、`e_gmag`、`rmag`、`e_rmag`、`imag`、`e_imag`、`zmag`、`e_zmag`、`ymag`、`e_ymag`，参考历元 `J2012.0`）
   - `V/156/dr7lrs`：**LAMOST DR7 Low-Resolution Spectra**（`RAJ2000`、`DEJ2000`、`Class`、`SubClass`、`Teff`、`e_Teff`、`logg`、`e_logg`、`FeH`、`e_FeH`、`RV`、`e_RV`，参考历元 `J2000.0`）
   - `J/A+A/640/A1/nodup`：**Cantat-Gaudin+2020 疏散星团成员表**（`GaiaDR2`、`RA_ICRS`、`DE_ICRS`、`Gmag`、`BP-RP`、`proba`、`Cluster`，参考历元 `J2015.5`）
2. **自定义 VizieR 表 ID 查询**：
   - 白名单校验表 ID 格式（`^[A-Za-z0-9_+./-]{3,64}$`），先查 `TAP_SCHEMA.columns` 定位赤经/赤纬列与单位（找不到坐标列则清晰报错，不猜测）；
   - 仅允许受控圆锥检索（中心赤经/赤纬或由 SIMBAD 解析天体名得到坐标，检索半径 `0.05'–60'`，返回行数上限 `1–500`，用 `TOP (limit + 1)` 准确检测截断状态 `has_more`）；
   - 返回统一结构化 `VizierQueryResult`，含真实列单位、参考历元、CDS 官方目录链接、实际执行的 ADQL 查询式与圆锥候选源位置告警。
3. **MCP 与工具目录同步**：将 `query_vizier` 纳入 [tool_catalog.py](../src/astroagent/tool_catalog.py) 与本地 `stdio` [mcp_server.py](../src/astroagent/mcp_server.py)（`read_only_hint=True`、`idempotent_hint=True`）。

---

## 4. 确定性天文数据算子设计

所有算子在服务端独立模块（`src/astroagent/table_ops.py`）中以确定性算法运行，记录输入表 SHA-256、完整参数与软件版本（`astropy` / `numpy` / `scipy`）。

### 4.1 描述统计、相关性与分布检验（`stats`）

- **单列统计**：对选定数值列计算总行数、有效有限值数、缺失/NaN/Inf 数、均值、样本标准差（`ddof=1`）、最小值、5% / 25% / 50%（中位数）/ 75% / 95% 分位数、四分位距（IQR）与最大值；
- **双列相关性**：指定 `(x_col, y_col)`，仅在两列同时有限的配对行上计算 Pearson $r$ 与双尾 $p$ 值、Spearman 秩相关 $\rho$ 与双尾 $p$ 值，显式报告有效配对数 $N_{\mathrm{valid}}$ 与被跳过行数；
- **双样本 KS 检验**：支持比较「两张表的同一物理量列」或「同一张表按分类/条件拆分的两个子样本」，运行 `scipy.stats.ks_2samp`，报告统计量 $D$、$p$ 值与两侧样本量。

### 4.2 安全结构化筛选与派生列（`filter_derive`）

- **结构化筛选**：采用 JSON 规则列表（`AND` / `OR` 组合），支持 `eq` / `ne` / `lt` / `le` / `gt` / `ge` / `between` / `is_null` / `not_null` / `in` / `contains`，以及两个数值列的比值/差值条件（如 `parallax / parallax_error >= 10`）；
- **白名单派生列**：支持受限 AST 解析器计算的常用天文派生表达式（仅允许四则运算、`abs`、`sqrt`、`log10`、`ln`、`exp`、`sin`、`cos`、`tan`、`hypot`、`pow` 及已有数值列引用，**严禁任意 Python 执行**），支持显式标注新列物理单位（如 `G_abs = phot_g_mean_mag + 5 * log10(parallax) - 10`，并自动提醒「视差倒数近似、未做消光与零点校正」）；
- **输出**：返回筛选前后行数、每条条件的剔除计数与可保存的派生表。

### 4.3 天球坐标转换与角距计算（`coordinates`）

使用 `astropy.coordinates.SkyCoord` 确定性执行：
- **坐标系转换**：支持输入 `ICRS` / `FK5 (J2000)` / `Galactic`（单位支持 `deg` 或 `hourangle,deg` 性别制字符串），输出转换后的坐标列（如 `gal_l_deg`、`gal_b_deg` 或 `ra_icrs_deg`、`dec_icrs_deg`），显式保留单位 `deg`；
- **到参考点角距**：输入参考中心 `(ra0, dec0)`，计算每行到中心的大圆角距列 `sep_ref_arcsec`（单位 `arcsec`）与方位角 `pa_ref_deg`（`position_angle`，东偏北 `deg`）；
- 坐标含缺失或非有限值的行输出空值并在摘要中计数，不悄悄丢行。

### 4.4 天空坐标交叉匹配（`crossmatch`）

使用 `astropy.coordinates.match_coordinates_sky` 与 `search_around_sky` 实现精确球面匹配：
- **输入参数**：左表 ID、右表 ID、左右表 RA/Dec 列名、坐标单位与坐标系、搜索半径 `radius_arcsec`（`0.05"–300"`）、匹配模式 `nearest`（最近邻一对一）或 `all_within_radius`（半径内全部候选，单左行最多保留前 `10` 个候选并标注截断）、连接类型 `inner` / `left`、右表列名冲突前缀（默认 `r_`）；
- **防错配诊断输出**：
  - 自动附加 `match_sep_arcsec`（匹配角距）、`match_candidate_count`（搜索半径内右表候选总数）、`match_next_sep_arcsec`（若半径内 ≥ 2 个候选或次近邻存在，给出次近邻角距，方便评估拥挤视场错配风险）；
  - 输出汇总指标：左表有效坐标行数、右表有效坐标行数、成功匹配行数、匹配率、多候选冲突行数、匹配角距中位数与 90% 分位数；
- **强制科学警示**：比对左右表元数据中的 `ref_epoch`（如 Gaia `J2016.0` vs 2MASS `J2000.0`），当历元不同或任意一方未知时强制写入「两表参考历元不同或未知，未执行自行传播，高自行源或拥挤星场可能漏配或错配」警告。

### 4.5 确定性科学拟合（`fit`）

使用 `numpy` / `scipy.optimize.curve_fit` 执行可复现曲线拟合：
- **支持 4 类模型**：
  1. `linear`：$y = a x + b$（提供 `y_err` 时自动执行加权最小二乘 WLS，要求 `y_err > 0`）
  2. `polynomial`：$y = \sum_{k=0}^{d} c_k x^k$（阶数 $d \in \{2, 3, 4\}$，支持权重）
  3. `power_law`：$y = A x^\alpha$（要求 $x > 0$，以对数线性初值启动非线性加权最小二乘，返回原始空间参数与误差）
  4. `gaussian`：$y = b + A \exp\!\left(-\frac{(x-\mu)^2}{2\sigma^2}\right)$（自动由样本极值与半高宽估算稳健初值，支持用户可选覆盖初值，同时报告 FWHM $= 2\sqrt{2\ln 2}\,\sigma$）
- **输出指标**：各参数估计值与 `1σ` 标准误差（由协方差矩阵对角线开方；若未提供 `y_err`，按残差方差缩放协方差并明确标注 `unweighted`）、$R^2$、RMSE、加权约化 $\chi^2_\nu$（提供 `y_err` 时）、自由度 `dof`、有效点数、剔除无效行数及拟合收敛状态；
- **派生表与绘图衔接**：一键生成包含原列、`y_fit`、`residual`（及提供 `y_err` 时的 `normalized_residual`）的新表，并可直接送入隔离绘图生成「散点 + 拟合曲线 + 残差」双面板图形。

---

## 5. 数据模型、存储隔离与 API 契约

### 5.1 租户私有 Schema 增量表（`src/astroagent/table_store.py`）

完全复用 V2.2 长期记忆的租户自动建表模式（[memory_store.py](../src/astroagent/memory_store.py)），在每个用户的私有 PostgreSQL schema（`aa_<32-hex>`）内幂等创建 3 张表，**不修改 `public.*` 任何表，不触动现有 `plot_*` 与项目归档格式 1–6**：

```sql
CREATE TABLE IF NOT EXISTS table_meta (
    version INTEGER PRIMARY KEY CHECK (version = 1)
);

CREATE TABLE IF NOT EXISTS analysis_datasets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    source TEXT NOT NULL,           -- upload | gaia_turn | gaia_snapshot | vizier | derived
    source_sha256 TEXT NOT NULL,
    data_sha256 TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    column_count INTEGER NOT NULL,
    record TEXT NOT NULL,           -- JSON: 列结构、单位、历元、来源、血缘、告警
    data_gz BYTEA NOT NULL,         -- gzip 压缩的规范化 ECSV/CSV 字节流
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analysis_datasets_proj
    ON analysis_datasets (project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    operator TEXT NOT NULL,         -- stats | filter_derive | coordinates | crossmatch | fit
    state TEXT NOT NULL,            -- completed | failed
    request_sha256 TEXT NOT NULL,
    output_dataset_id TEXT REFERENCES analysis_datasets(id) ON DELETE SET NULL,
    record TEXT NOT NULL,           -- JSON: 输入摘要、参数、结果指标、告警、软件版本
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_proj
    ON analysis_runs (project_id, created_at DESC);
```

- **自动配额计量**：表位于 `aa_<hex>` 内，自动被 [usage.py](../src/astroagent/usage.py) 的 `storage_bytes()` 与项目存储预算计入；删除项目时随 `ON DELETE CASCADE` 自动清理。
- **桥接隔离绘图**：提供 `POST /api/v1/projects/{project_id}/tables/{dataset_id}/send-to-plot`，若 `plot_meta` 尚未初始化则自动幂等初始化，并把目标表的规范化 CSV 写入 `plot_datasets`（若行数超过绘图现有上限 `10,000` 或体积超过 `5 MiB`，清晰提示先用「筛选」算子降采样/过滤后再送去绘图）。

### 5.2 核心 HTTP 接口（契约定稿后运行 `generate_frontend_types.py`）

- `GET /api/v1/tables/vizier/presets`：返回内置常用 VizieR 星表清单与默认列/历元说明；
- `POST /api/v1/tables/vizier/query`：执行受控只读 VizieR 圆锥检索（可直接返回结果，或指定 `project_id` 同步保存为项目数据表）；
- `GET /api/v1/projects/{project_id}/tables`：返回项目数据表清单与最近分析运行记录；
- `POST /api/v1/projects/{project_id}/tables/inspect`：上传 FITS/VOTable/ECSV/CSV/TSV 预检（返回 HDU 列表、行列数、列名与单位，用于多 HDU 或宽表选列）；
- `POST /api/v1/projects/{project_id}/tables/upload`：按确认后的 HDU/列子集正式导入并持久化；
- `POST /api/v1/projects/{project_id}/tables/from-gaia`：从指定会话轮次或项目命名快照导入 Gaia DR3 结果表；
- `GET /api/v1/projects/{project_id}/tables/{dataset_id}` & `GET .../preview?offset=0&limit=50`：获取表元数据、血缘与分页预览；
- `DELETE /api/v1/projects/{project_id}/tables/{dataset_id}`：删除指定数据表；
- `POST /api/v1/projects/{project_id}/tables/runs/{operator}`：执行确定性算子（`stats` / `filter_derive` / `coordinates` / `crossmatch` / `fit`），支持 `save_derived: true` 与 `derived_name` 幂等保存派生表；
- `POST /api/v1/projects/{project_id}/tables/{dataset_id}/send-to-plot`：一键桥接至项目隔离绘图；
- `GET /api/v1/projects/{project_id}/tables/{dataset_id}/export?format=csv|ecsv|fits` 与 `GET /api/v1/projects/{project_id}/tables/runs/{run_id}/bundle`（ZIP 复现包，含 `manifest.json` 与 SHA-256）。

### 5.3 Agent 联动与安全边界

- **不可信数据防线**：表格单元格文本、FITS 注释头、VizieR 描述字段均作为不可信参考数据处理，严禁提升权限或绕过确认；
- **新增内置技能 `astronomy-table-analysis`**（`src/astroagent/skills_data/astronomy-table-analysis/SKILL.md`）：指导模型先用 `list_project_tables` 查清真实表 ID、列名与单位，需要外部多波段星表时调用只读 `query_vizier`，涉及筛选/坐标/交叉匹配/拟合时调用 `prepare_table_analysis` 生成可审阅参数卡片交由用户确认执行，严禁模型在回复中自行估算拟合系数或匹配率；
- **与绘图技能无缝衔接**：派生表保存后，`prepare_scientific_plot` 新增 `source="project_table"` 引用方式，可直接基于交叉匹配表或拟合残差表生成 Matplotlib / Gnuplot 绘图脚本。

---

## 6. 实施顺序与验收门槛

### 6.1 分阶段里程碑

| 阶段 | 核心交付 | 退出条件 |
| --- | --- | --- |
| **M0 契约与存储** | `table_schemas.py`、`table_store.py`（租户 3 表自动初始化）、`table_io.py`（FITS/VOTable/ECSV/CSV/TSV 安全解析与导出） | 覆盖恶意 XML/XXE、非表格 FITS、>64 列选列、64 位 `source_id` 精度保真、容量与配额拦截单测 |
| **M1 VizieR 只读检索** | `vizier.py`（5 个内置星表 + 自定义表 ID + `defusedxml` VOTable 解析）、接入 `tool_catalog.py`、`mcp_server.py` 与 `ResultPanel` | 离线回放 VOTable 样例、截断检测、非法表 ID 拦截、配额扣减及本地 MCP 协议单测通过 |
| **M2 确定性算子引擎** | `table_ops.py`（统计/相关/KS、白名单筛选与 AST 派生列、ICRS↔Galactic、天空交叉匹配、4 类拟合）、桥接 `PlotService` 与 ZIP 导出 | 通过全部天体物理数值基准单测（见 6.2），确认无 `eval`/`exec` 且无模型口算路径 |
| **M3 路由、技能与对话接入** | `api/tables.py`、扩展 `attachments.py`、新增 `astronomy-table-analysis` Skill 与 `prepare_table_analysis` 工具、同步 OpenAPI 与前端生成类型 | `generate_frontend_types.py --check`、隔离 PostgreSQL 多账号隔离与项目级联删除测试通过 |
| **M4 工作台一体化界面与卡片** | 沿用绘图与 N 体的一体化架构（不单设页面）：`TableResultPanel.vue`（嵌入 `ResultPanel`）、`ChatTableAnalysisCard.vue`、`ResultPanel` VizieR/Gaia 一键存表、`ProjectManageDrawer` 与 `/tables` 重定向 | `typecheck`、`lint`、Vitest 与 Playwright 端到端全流程（上传→交叉匹配→拟合→送去绘图）通过 |
| **M5 全量回归与发布** | 离线单测、隔离 PostgreSQL、Playwright、实机本机 5173 视觉核查与文档更新 | 满足全部发布门槛，证据归档至 `docs/test-records/v2.3.0/<类型>/<UTC时间>/` |

### 6.2 科学数值验收标准

1. **天球坐标变换基准**：验证若干标准参考点（如银心方向 $\alpha = 266.405^\circ, \delta = -28.936^\circ \to l \approx 0^\circ, b \approx 0^\circ$；银北极 $\alpha = 192.8595^\circ, \delta = +27.1283^\circ \to b \approx +90^\circ$）与 `ICRS → Galactic → ICRS` 往返误差 `< 10⁻¹⁰ deg`。
2. **天空交叉匹配基准**：使用构造的合成星表（含精确重合、已知角距偏移 $0.5'' / 2.0''$、跨 $\alpha = 0^\circ / 360^\circ$ 边界源、高赤纬 $\delta = +89.5^\circ$ 源、半径内双候选拥挤源及未匹配源），核对球面角距误差 `< 10⁻⁶ arcsec`、跨 0°/360° 与极区零漏配、多候选 `match_candidate_count` 与 `match_next_sep_arcsec` 精确一致，并验证历元不同告警强制出现。
3. **科学拟合基准**：
   - 无噪声/已知高斯噪声线性加权数据：验证斜率、截距与解析 WLS 公式一致（相对误差 `< 10⁻¹⁰`），$\chi^2_\nu$ 与自由度精确；
   - 已知解析幂律与单高斯谱线数据：验证拟合参数、FWHM 与理论真值误差在预设容差内；
   - 异常输入（含 `NaN` / `Inf`、有效点数不足、非正 `y_err`、幂律非正 `x`）返回明确结构化报错，不崩溃也不静默输出虚假值。
4. **64 位整数与单位保真**：Gaia DR3 `source_id`（19 位整数）经 CSV / ECSV / FITS / 交叉匹配 / 导出往返后每一位字符完全一致；单位与 FITS/VOTable 元数据全程保留。

### 6.3 工程与安全验收标准

- **多账号隔离**：在隔离 PostgreSQL 中以两个账号验证数据表、分析运行、派生表、导出与桥接绘图严格按租户 schema 隔离，跨账号访问返回 `404`。
- **存储与删除一致性**：导入与派生表计入账号 `storage_mib` 配额；删除项目后 `analysis_datasets`、`analysis_runs` 自动级联清理且不影响既有 `plot_*` 与格式 1–6 项目归档。
- **离线测试合规**：默认 `pytest -m "not live and not postgres"` 禁止任何外部 HTTP，VizieR 测试均使用本地固定 VOTable 夹具；实网 VizieR 查询（如 M45 2MASS / AllWISE）单独归入 `-m live` 验收。
- **兼容性**：既有 Gaia、SIMBAD、ADS、隔离绘图、N 体模拟、长期记忆、Skills 与外部 MCP 全量回归通过。

开发阶段按 [AGENTS.md](../AGENTS.md) 约定不主动运行全量测试，预览统一使用本机 `http://127.0.0.1:5173`；验收与正式发布均按用户明确安排执行。[开发与发布手册](DEVELOPMENT_AND_RELEASE.md)
