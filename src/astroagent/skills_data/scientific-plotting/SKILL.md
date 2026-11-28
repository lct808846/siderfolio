---
name: scientific-plotting
description: 当用户需要基于 Gaia、VizieR、项目数据表或上传的表格附件生成科研绘图方案与独立 Python/Gnuplot 脚本时使用。
metadata:
  title: 科研绘图准备
  version: "1.0.0"
  category: visualization
  allowed_tools:
    - query_simbad
    - query_gaia
    - query_vizier
    - list_project_tables
    - prepare_scientific_plot
  intent_keywords:
    - 绘图
    - 画图
    - 作图
    - 图表
    - 赫罗图
    - 色星等图
    - cmd
    - 散点图
    - 直方图
    - 误差棒
    - matplotlib
    - gnuplot
  example_prompts:
    - 根据刚才 M45 的 Gaia DR3 数据生成一份色星等图（BP-RP vs G）Python 绘图脚本
    - 用 Matplotlib 为当前项目交叉匹配派生表绘制颜色-星等图并标出物理单位
    - 为刚才上传的测光表生成带误差棒的 Gnuplot 散点图方案
  delivery_summary: 生成保留真实数据引用与单位的独立 Python/Gnuplot 科研绘图脚本，交由用户在卡片中核对后在隔离容器中出图。
  boundaries: 确认前不执行绘图脚本；仅使用真实列名、单位与明确筛选条件，不编造数据点、不默认删除负视差或自动校正消光。
---

# 科研绘图准备研究步骤

本技能用于规范科研绘图方案与脚本编写流程，所有实际执行均必须经过用户审阅、确认与无网隔离绘图容器运行。

## 1. 确认数据来源

1. 优先确认数据来源：本轮 Gaia 数据（`current_turn_gaia`）、历史轮次 Gaia 数据（`history_turn_gaia`）、项目数据表（`project_table` / `project_dataset`，可先调用 `list_project_tables` 获取真实 `dataset_id` 与列名）或用户上传的表格附件（`attachment_csv`）。
2. 若用户指定了具体天体或视场但尚无数据，先按需调用只读工具 `query_simbad`、`query_gaia` 或 `query_vizier` 获取真实样本。

## 2. 生成独立可复现绘图脚本

1. 调用 `prepare_scientific_plot` 生成无 Markdown 围栏的完整独立脚本（固定读取 `/input/data.csv`，同时输出 `/output/figure.png` 与 `/output/figure.pdf`）。
2. Python 脚本仅使用标准库、`numpy` 与 `matplotlib`（`Agg` 后端，中文标注优先使用 `WenQuanYi Zen Hei`）；Gnuplot 脚本由 `gnuplot` 直接执行且不调用外部 shell。
3. 核查并说明数据引用、真实列名、坐标轴标签、物理单位、星等轴反转方向、缺失值处理及是否应用了用户指定的筛选条件；严禁编造数据列或未经请求的科学筛选。
4. 明确提示用户在审阅卡片中核对或修改脚本后，再点击确认在隔离容器中出图。
