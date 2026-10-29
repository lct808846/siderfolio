# AstroAgent 项目开发计划 V0.1

## 1. 项目简介

**项目名称：** AstroAgent

**项目类型：** 天文科研 AI Agent 平台

**开发方式：** 个人开发，使用 Codex 辅助编码、测试和代码审查。

**项目目标：** 构建能够理解科研人员自然语言指令、自动调用天文数据库工具并生成可追溯科研结果的智能体系统。

## 2. V0.1 功能需求

### 2.1 核心功能

- 支持用户通过自然语言提出天文查询问题。
- 接入大语言模型 API。
- 使用 Tool Calling 自动判断是否需要查询天文数据库。
- 实现 SIMBAD 天体查询工具。
- 返回真实天体信息及来源。
- 提供 FastAPI 接口供外部调用。
- 对无效天体名称、API 超时和查询失败进行错误处理。

### 2.2 暂不实现

- Web 前端
- 多用户系统
- Multi-Agent
- MCP
- RAG
- 向量数据库
- 复杂科研工作流

## 3. 技术选型

| 模块       | 技术                     |
| ---------- | ------------------------ |
| 开发语言   | Python                   |
| 后端框架   | FastAPI                  |
| Agent 框架 | LangChain                |
| 模型       | 支持 Tool Calling 的 LLM |
| 天文查询   | astroquery + SIMBAD      |
| 数据验证   | Pydantic                 |
| 自动化测试 | pytest                   |
| 版本管理   | Git + GitHub             |

## 4. 系统工作流程

用户提交问题 → FastAPI 接收请求 → Agent 分析任务 → LLM 判断是否需要调用工具 → Python 执行 SIMBAD 查询 → 查询结果返回 Agent → LLM 生成回答 → FastAPI 返回结果。

## 5. API 设计

**POST /api/v1/chat**

输入：用户自然语言问题。

输出：Agent 的回答、相关查询结果及数据来源。

**GET /health**

输出：服务健康状态。

## 6. V0.1 验收标准

- 服务能够正常启动。
- 能够通过 FastAPI `/docs` 测试接口。
- 查询 Betelgeuse 时能够调用 SIMBAD。
- 能够返回真实天体信息，不使用虚构数据。
- 对数据库查询失败有明确错误提示。
- 有基本自动化测试。
- 代码可以通过 Git 管理。
- README 包含安装和运行说明。

## 7. 后续迭代

以下保留 V0.1 时的原始方向。2026-10-28 起的细分版本、范围和退出标准统一见 [版本路线图](ROADMAP.md)，下一步见 [V0.5 开发文档](PROJECT_PLAN_V0.5.md)。

V0.2：ADS 文献检索。

V0.3：Gaia 数据查询与分析。

V1.0：科研工作流、知识库和用户界面。

V2.0：权限、安全、Tracing、Evaluation、异步任务及生产部署。

## 8. V0.1 实现与验收（2026-10-26）

- [x] `POST /api/v1/chat` 接收自然语言问题。
- [x] 通过 LangChain `ChatOpenAI.bind_tools` 接入 DeepSeek 非思考模式工具调用。
- [x] 模型自动选择 `query_simbad`，程序校验参数并执行 astroquery 名称查询。
- [x] 返回真实标识符、ICRS 坐标、类型、光谱类型、坐标文献编号与 SIMBAD 来源链接。
- [x] 无匹配、外部模型/数据库失败和超时有明确错误信息；已取得的数据在回答生成失败时保留。
- [x] 服务启动、健康检查和接口文档可用。
- [x] 离线自动化测试、真实服务测试、实际 Uvicorn HTTP 验收均通过。
- [x] README 包含安装、配置、运行、接口调用与测试说明。

实现不增加第 2.2 节排除的功能。查询字段范围和当前测试证据见 [README](../README.md) 与 [测试说明](TESTING.md)。GitHub Actions 配置已加入，远程检查需推送后执行。
