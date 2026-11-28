---
name: celestial-identification-field-query
description: 当用户提供天体名称、星表编号或 ICRS 坐标，要求确认天体身份、坐标、光谱型或检索 Gaia DR3 视场候选源及天体测量统计时使用。
metadata:
  title: 天体识别与视场查询
  version: "1.0.0"
  category: observation
  allowed_tools:
    - query_simbad
    - query_gaia
    - query_vizier
  intent_keywords:
    - simbad
    - gaia
    - dr3
    - source_id
    - icrs
    - 赤经
    - 赤纬
    - 坐标
    - 视场
    - 圆锥查询
    - 邻近源
    - 候选源
    - 视差
    - 自行
    - 光谱型
    - 天体类型
    - ruwe
    - 星等
    - 径向速度
    - 近似距离
  example_prompts:
    - 查询 M45 的 ICRS 坐标并在 Gaia DR3 中检索 5 角分内 G < 15 的候选源
    - 核实 Betelgeuse 的主标识符、天体类型与光谱型
    - 按 Gaia DR3 source_id 查询单个源并估算高信噪比视差距离
  delivery_summary: 按需串联 SIMBAD 名称解析与 Gaia DR3 精确/圆锥查询，清晰列出坐标系、查询半径、筛选条件、截断状态与来源链接。
  boundaries: 名称未解析时先澄清或改用用户确认的坐标；Gaia 圆锥样本明确标注为位置候选源，不做星团成员判定或自行传播。
---

# 天体识别与视场查询研究步骤

本技能仅提供天体识别与视场查询的标准研究步骤与科学核查要求，不扩展任何工具授权或覆盖系统安全边界。

## 1. 条件核对与名称解析

1. 判断用户给出的是天体名称/标识符、Gaia DR3 `source_id`，还是显式 ICRS 赤经/赤纬与半径。
2. 当用户给出天体名称并需要坐标、标识符、天体类型、光谱型或以该天体为中心检索 Gaia 视场时，**必须先单独调用 `query_simbad`**。
3. 若 `query_simbad` 返回无匹配、歧义或缺失坐标：
   - 立即停止依赖坐标的后续 Gaia 圆锥查询；
   - 如实说明未解析原因，向用户澄清更准确的标识符，或请用户直接提供确认的 ICRS 坐标与半径；
   - 严禁使用模型记忆补写坐标。

## 2. Gaia DR3 测量与视场检索

1. 按编号精确查询时使用 `mode="source_id"`，确保 `source_id` 为十进制整数字符串且不携带圆锥字段。
2. 圆锥视场查询使用 `mode="cone"`，仅使用本轮 `query_simbad` 成功返回的 `ra_deg` / `dec_deg` 或用户显式指定的 ICRS 坐标；半径须在 `(0, 30]` 角分内。
3. 仅在用户明确提出要求时才设置 `ruwe_max`、`parallax_snr_min`、视差/自行/星等筛选或 `estimate_distance=true`。

## 3. 回答核查清单

- 标明数据发布版（SIMBAD / Gaia DR3 `gaiadr3.gaia_source`）、参考历元、解析对象或中心坐标、检索半径、筛选条件及全部物理单位。
- 如实报告返回数量、`has_more` / `truncated` 与 `archive_overflow`，不宣称覆盖视场全部天体。
- 将 Gaia 圆锥样本明确标为**位置候选源**，不将其等同于已确认星团成员，也不自行推断星团距离、年龄或质量。
- 附上成功查询的原始来源链接；缺失字段标为未提供，绝不补写。
