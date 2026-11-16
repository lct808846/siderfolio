# Repository Guidelines

## 项目结构与模块组织

- `src/astroagent/`：FastAPI 后端、天文查询、会话、知识库、身份认证和绘图服务；HTTP 路由位于 `api/`。
- `frontend/src/`：Vue 3 + TypeScript 前端；`views/` 存放页面，`components/` 存放组件，`stores/` 管理状态，`api/` 封装请求。
- `tests/`：Python 测试；`frontend/tests/`：前端单元测试与浏览器测试。
- `containers/`、`compose*.yaml`：容器部署与隔离绘图运行环境；`scripts/`：开发、生成和验收脚本。
- `docs/`：版本计划、实施说明和验收记录；`outputs/` 为本机临时产物目录。

## 安装、开发与检查命令

使用 Python 3.12+、Node.js 24.x（至少 24.15）。以下命令默认在仓库根目录运行；npm 命令需先进入 `frontend/`。

```powershell
python -m pip install -e ".[dev]"    # 安装后端与开发依赖
python -m uvicorn astroagent.main:app --host 127.0.0.1 --port 8000 --workers 1
cd frontend
npm ci                            # 按锁文件安装前端依赖
npm run dev                       # 启动 Vite 开发服务
npm run build                     # 类型检查并生成生产资源
npm run serve                     # 提供生产静态资源
```

当前身份认证部署还需准备私有配置，遵循 `docs/development/v1.6.0/OPERATIONS.md`。

## 编码风格与命名

Python 使用四空格缩进、`snake_case` 函数和模块名、`PascalCase` 类名；Ruff 目标为 Python 3.12，行宽 100。前端沿用两空格缩进、单引号和省略行尾分号的现有风格，Vue 组件使用 `PascalCase.vue`。使用 ESLint 与 TypeScript 检查。

API 契约变化后运行 `python scripts/generate_frontend_types.py`，同步 OpenAPI 快照及生成类型，不直接手改 `frontend/src/types/generated.ts`。

## UI 设计与一致性

新增或修改界面前阅读并遵循 [UI 设计规范](docs/UI_DESIGN_SPEC.md)。复用共用主题变量、导航、面板标题及已有业务组件；通用视觉值集中维护，页面仅定义局部布局。页面族例外须按规范登记，UI 变更按规范清单审查；未实际执行的视觉检查标为待验收。按用户 2026-11-15 最新要求，完成开发后直接构建并更新当前部署中的相关容器，检查启动健康状态；开发期不主动测试和验收的约定继续适用。

## 测试规范

开发阶段不主动运行测试和验收。开发完成后按用户要求构建并更新相关容器，保留现有私有配置和数据卷；构建内置的类型检查及启动健康检查属于部署步骤，不代表功能验收。用户明确安排测试或验收时使用：

- 后端：`python -m pytest -q`；测试文件命名为 `tests/test_*.py`。
- Python 检查：`python -m ruff check src tests scripts` 与 `python -m ruff format --check src tests scripts`。
- 前端：在 `frontend/` 执行 `npm run typecheck`、`npm run lint`、`npm test`（Vitest）；浏览器测试使用 `npm run test:browser`（Playwright），先构建并安装 Chromium。

默认离线测试禁止外部 HTTP。`live`、`postgres`、`identity` 标记区分真实服务、隔离数据库与身份边界；数据库验收使用专用库。旧业务替身测试不证明生产身份隔离通过。当前未配置数值覆盖率门槛。证据存入 `docs/test-records/v<版本>/<类型>/<UTC时间>/`，保留失败和跳过项，不覆盖历史。

## 提交与合并请求

历史提交使用简短、祈使式英文主题，例如 `Fix missing PNG validation in workflow archives`；沿用该风格，无须添加 Conventional Commits 前缀。保持提交范围集中，保留工作区已有修改。

合并请求应说明问题、行为变化、验证结果及限制，关联相关 issue；界面变更附截图，契约或部署变更同步文档。未执行的检查须明确标注。

## 配置与数据保护

密钥、ADS token、数据库凭据和邮件配置仅保存在服务端私有配置中；`VITE_*` 变量会暴露给浏览器。运行时使用 PostgreSQL/pgvector，不新增 SQLite 回退。数据库初始化、迁移、清空和恢复必须获得明确授权；测试不得连接日常业务库。
