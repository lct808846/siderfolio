---
name: scientific-plotting-nbody-prep
description: 当用户需要基于 Gaia/附件数据生成科研绘图脚本，或准备可执行的小规模孤立 N 体数值模拟（REBOUND / PeTar）草案时使用。
metadata:
  title: 科研绘图与 N 体实验准备
  version: "1.0.0"
  category: modeling
  allowed_tools:
    - query_simbad
    - query_gaia
    - prepare_scientific_plot
    - prepare_nbody_simulation
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
    - n体
    - n-body
    - nbody
    - 轨道模拟
    - 数值模拟
    - rebound
    - petar
    - 质心系
    - 三体
    - 双星轨道
  example_prompts:
    - 根据刚才 M45 的 Gaia DR3 数据生成一份色星等图（BP-RP vs G）Python 绘图脚本
    - 设计一个太阳-地球-木星三体系统演化 12 年的 REBOUND 模拟参数方案
    - 准备一个 8 粒子孤立疏散星团核区的 PeTar 初始条件草案
  delivery_summary: 生成保留真实数据引用与单位的独立绘图脚本，或物理自洽的 2–128 粒子 N 体模拟草案，交由用户在原入口审阅与确认执行。
  boundaries: 确认前不执行绘图脚本也不提交后台计算任务；仅使用真实列与孤立牛顿点质量假设，运行后通过原任务记录核查轨迹与能量守恒。
---

# 科研绘图与 N 体实验准备研究步骤

本技能用于规范科研绘图方案编写与小规模 N 体数值实验准备流程，所有实际执行均必须经过既有用户审阅、确认、配额与隔离运行入口。

## 1. 科研绘图准备

1. 优先确认数据来源：本轮 Gaia 数据（`current_turn_gaia`）、历史轮次 Gaia 数据（`history_turn_gaia`）或用户上传的 CSV/TSV 附件（`attachment_csv`）。若用户指定了具体天体或视场但尚无数据，先按需调用 `query_simbad` 与 `query_gaia`。
2. 调用 `prepare_scientific_plot` 生成无 Markdown 围栏的完整独立脚本（读取 `/input/data.csv`，输出 `/output/figure.png` 与 `/output/figure.pdf`）。
3. 核查并说明数据引用、真实列名、坐标轴标签、物理单位、星等轴反转方向、缺失值处理以及是否应用了用户指定的筛选条件；不编造数据列或未经请求的筛选。
4. 明确提示用户在审阅卡片中核对或修改脚本后，再点击确认在隔离容器中出图。

## 2. N 体数值实验准备

1. 确认粒子数处于现有孤立点质量模型范围（2–128 粒子），固定采用标准单位：质量 `M_sun`、位置 `AU`、速度 `AU/yr`、时长 `yr`（引力常数 `G = 4π²`）。
2. 根据体系特征与用户指定选择引擎：少体、行星或双星默认 `rebound`，多体星团或近距离交会场景可选 `petar`；合理设置质心静止系，确保粒子 ID 唯一且初始间距 `> 1e-5 AU`。
3. 调用 `prepare_nbody_simulation` 输出完整参数方案，清晰列出粒子参数、单位、引擎、采样点数与孤立点质量物理假设（不宣称包含银河系潮汐场、气体阻尼或恒星演化）。
4. 绝不编造未执行的轨道或能量诊断结果；提示用户在模拟卡片中核对并确认提交，待后台完成后在任务记录查看轨迹图与能量/角动量守恒诊断。
