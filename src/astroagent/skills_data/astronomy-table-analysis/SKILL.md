---
name: astronomy-table-analysis
description: 当用户需要导入/检查 FITS/VOTable/ECSV/CSV 天文数据表、检索 VizieR 多波段星表（2MASS/AllWISE/Pan-STARRS/LAMOST/Cantat-Gaudin+2020），或执行确定性筛选、坐标变换、天空交叉匹配与科学拟合时使用。
metadata:
  title: 天文数据表分析与交叉匹配
  version: "1.0.0"
  category: analysis
  allowed_tools:
    - query_simbad
    - query_gaia
    - query_vizier
    - list_project_tables
    - prepare_table_analysis
    - prepare_scientific_plot
  intent_keywords:
    - vizier
    - 2mass
    - allwise
    - pan-starrs
    - lamost
    - fits
    - votable
    - ecsv
    - 交叉匹配
    - crossmatch
    - 坐标转换
    - 银道坐标
    - 银经
    - 银纬
    - 拟合
    - 线性拟合
    - 高斯拟合
    - 幂律拟合
    - ks检验
    - 相关性
    - 派生列
    - 数据表
  example_prompts:
    - 检索 M45 中心 10 角分内的 VizieR 2MASS (II/246/out) 与 AllWISE (II/328/allwise) 源
    - 先查看当前项目的数据表，再准备一个 Gaia 与 2MASS 的 2 角秒天空坐标交叉匹配方案
    - 对当前项目拟合表做线性 WLS 拟合，并基于派生残差表生成双面板 Matplotlib 绘图脚本
  delivery_summary: 调用只读 VizieR 检索或生成由后端 Astropy/NumPy/SciPy 确定性执行的表分析确认卡片，绝不在模型回复中口算统计或拟合参数。
  boundaries: 确认前不写入派生表或执行交叉匹配/拟合；严禁模型估算回归系数、KS 检验 p 值或匹配率；跨历元交叉匹配必须保留自行未传播警示。
---

# 天文数据表分析与交叉匹配工作流

本技能规范多格式天文数据表分析、VizieR 星表检索与科学拟合流程，所有数值运算必须由服务端 `Astropy` / `NumPy` / `SciPy` 确定性执行，禁止口算或编造统计结果。

## 1. 先查清项目已有数据表与外部星表

1. 对话中上传的 FITS / VOTable / ECSV / CSV / TSV 附件，以及本会话内检索得到的 Gaia DR3 / VizieR 星表结果均会自动同步为当前项目数据表。若用户要求对已有或刚查到的表执行分析，直接先调用 `list_project_tables` 获取真实 `dataset_id`、列名、类型、单位与参考历元（`ref_epoch`），禁止猜测表 ID 或列名，也不要让用户手动“存入项目数据表”。
2. 需要补充 2MASS（`II/246/out`）、AllWISE（`II/328/allwise`）、Pan-STARRS DR1（`II/349/ps1`）、LAMOST DR7（`V/156/dr7lrs`）或 Cantat-Gaudin+2020 疏散星团成员表（`J/A+A/640/A1/nodup`）时，调用只读工具 `query_vizier`，返回结果随后可直接通过 `list_project_tables` 引用进入交叉匹配、统计或拟合。

## 2. 生成可审阅的表分析方案（`prepare_table_analysis`）

1. 根据目标选择算子，并严格按以下精确字段填写 `parameters`（不要添加额外未定义键）：
   - `stats`：单列分布统计、Pearson/Spearman 相关性与双样本 KS 检验；`parameters` 字段：`columns`、`corr_x`、`corr_y`、`ks_column`、`ks_other_dataset_id`、`ks_group_column`、`ks_group_a`、`ks_group_b`；
   - `filter_derive`：JSON 结构化筛选与安全 AST 数学表达式派生列；`parameters` 字段：`combine`（`"and"`/`"or"`）、`conditions`（`[{column, op, value?, value_max?, values?, rhs_column?}]`）、`derived_columns`（`[{name, expression, unit?, description?}]`）；
   - `coordinates`：`icrs` / `fk5` / `galactic` 坐标转换及大圆角距；`parameters` 字段：`lon_col`、`lat_col`、`input_frame`、`input_unit`（`"deg"`/`"hourangle_deg"`）、`output_frame`、`ref_ra_deg`、`ref_dec_deg`；
   - `crossmatch`：基于 `SkyCoord` 的球面交叉匹配（必须核对左右表参考历元差异，不隐藏未自行传播告警）；`dataset_id` 填左表 UUID、`secondary_dataset_id` 填右表 UUID，`parameters` 精确字段：`left_ra_col`、`left_dec_col`、`right_ra_col`、`right_dec_col`、`left_frame`（`"icrs"`）、`right_frame`（`"icrs"`）、`left_unit`（`"deg"`）、`right_unit`（`"deg"`）、`radius_arcsec`（如 `2.0`）、`mode`（`"nearest"` 或 `"all_within_radius"`）、`join_type`（`"inner"` 或 `"left"`）、`right_prefix`（如 `"r_"`）；
   - `fit`：确定性科学拟合；`parameters` 字段：`x_col`、`y_col`、`y_err_col`（有误差列时自动 WLS）、`model`（`"linear"`/`"polynomial"`/`"power_law"`/`"gaussian"`）、`degree`（2–4）、`initial_guess`。
2. 调用 `prepare_table_analysis` 生成确认卡片，明确列出输入表、算子参数、坐标历元与单位约定，提示用户点击「确认执行分析」查看真实计算数值。

## 3. 与隔离科研绘图衔接

当项目内已有派生表或拟合残差表并需要出图时，可调用 `prepare_scientific_plot` 并设置 `data_source_kind="project_table"` 与真实 `dataset_id`，由用户核对脚本后在隔离容器中出图。
