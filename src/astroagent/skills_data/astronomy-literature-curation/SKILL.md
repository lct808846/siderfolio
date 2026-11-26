---
name: astronomy-literature-curation
description: 当用户要求按主题、天体、作者、年份或 bibcode 检索 NASA ADS 天文文献，梳理研究脉络或将已核验条目保存到个人文献库时使用。
metadata:
  title: 天文文献检索与整理
  version: "1.0.0"
  category: literature
  allowed_tools:
    - search_ads
    - save_literature
  intent_keywords:
    - ads
    - bibcode
    - doi
    - 文献
    - 论文
    - 摘要
    - 综述
    - 引用
    - 被引
    - 发表
    - 保存文献
    - 加入文献库
    - 收藏论文
    - 书目
    - 参考文献
  example_prompts:
    - 检索 2022–2026 年关于双星团动力学的最新 ADS 论文并按被引次数排序
    - 查找与 NGC 869 相关的近期观测论文并整理核心摘要要点
    - 将刚才 ADS 检索结果的第 1 和第 3 篇保存到我的个人文献库
  delivery_summary: 调用 NASA ADS 检索并输出题目、年份、bibcode/DOI 与来源链接；在用户明确要求且范围唯一时幂等保存至个人文献库。
  boundaries: 严格区分书目元数据、摘要与已校验原文；不得编造文献或静默扩大保存范围，项目 RAG 原文沿用现有确认路径。
---

# 天文文献检索与整理研究步骤

本技能仅规范天文文献检索、摘要整理与受控入库步骤，不改变 `save_literature` 的服务端权限校验与项目 RAG 发送边界。

## 1. 检索式构造与执行

1. 使用 `search_ads` 执行真实检索，优先采用 `abs:`、`title:`、`author:`、`year:`、`bibcode:` 字段语法。
2. 中文主题可翻译为准确的天文学英文检索词，并在回答中明确写出实际执行的检索式与中英文对应关系。
3. 作者姓名、年份跨度或检索范围存在明显含糊时先向用户确认，不静默放宽年份或将关键词替换成 `object:`。

## 2. 书目整理与证据边界

1. 每次检索均写明实际 `query`、`database:astronomy` 范围、`sort`、本页数量与 `total_found`；明确 `total_found` 并非已阅读总数，不宣称穷尽文献。
2. 逐条列出本次返回的论文题目、第一作者/主要作者、年份、bibcode、DOI 及 ADS 原始链接，严格以工具返回字段为准。
3. 基于摘要的中文归纳必须标注“根据摘要”；若 `abstract_truncated` 或 `authors_truncated` 为 `true` 则如实说明截断；摘要缺失时仅呈现书目元数据，不推测正文方法或结论。
4. 若同时涉及项目本地知识库片段，清晰区分“ADS 书目/摘要”与“项目校验原文”，遵循现有 RAG 片段选择与发送确认流程。

## 3. 受控写入个人文献库

1. 仅在用户当前消息明确要求“保存/加入/收藏到个人文献库”且条目范围唯一确定（指定序号或 bibcode）时调用 `save_literature`。
2. 仅引用本轮或当前会话唯一历史 ADS 批次中的真实序号或 bibcode；指代不明时先向用户澄清，绝不自行猜测保存范围。
3. 最终是否入库以 `save_literature` 服务端回执为准，重放请求沿用现有幂等记录。
