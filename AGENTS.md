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

## 默认本地开发与容器更新

- 先阅读相关实现和本文件，采用增量修改，保留工作区已有修改。本机默认开发项目是 Windows Docker Desktop 的 `astroagent-dev`，唯一默认预览入口为 `http://127.0.0.1:5173`。独立数据库 `astroagent_dev` 保存从旧本机实例迁入的账号和科研数据。GCP 公网实例承载正式日常使用。[开发与发布手册](docs/DEVELOPMENT_AND_RELEASE.md#2-本机启动更新和预览)
- Vue、CSS、TypeScript 等已挂载的源码优先使用 Vite HMR，Python 源码由 Uvicorn 自动重载。完成一轮应用代码或开发配置修改后，在仓库根目录执行 `.\scripts\dev.ps1 -Action Update` 确保预览可用。依赖或构建配置变化时只重建对应开发镜像。普通源码更新复用已构建的镜像。纯文档修改无需更新运行服务。
- 本机脚本先检查 5173 的占用和开发数据库归属。需要交接端口时，只暂停已确认的旧入口容器。旧本机业务库已退役，开发更新沿用 `astroagent_dev` 的持久卷。数据库结构、身份部署配置或真实数据操作需要单独核对及授权。数据库试验使用独立测试环境和合成数据。
- Python、Gnuplot 执行镜像或绘图代理变更时，在隔离环境用 `.\scripts\dev.ps1 -Action BuildPlot -PlotImage <python|gnuplot|executor>` 构建对应目标。计算 Worker 替换前核对活动任务。
- 完成后报告改动文件、热更新或实际重建的服务、入口和未验证事项。构建或启动失败时保留现有数据卷、模型和科研文件，说明实际结果。

## 编码风格与命名

Python 使用四空格缩进、`snake_case` 函数和模块名、`PascalCase` 类名；Ruff 目标为 Python 3.12，行宽 100。前端沿用两空格缩进、单引号和省略行尾分号的现有风格，Vue 组件使用 `PascalCase.vue`。使用 ESLint 与 TypeScript 检查。

API 契约变化后运行 `python scripts/generate_frontend_types.py`，同步 OpenAPI 快照及生成类型，不直接手改 `frontend/src/types/generated.ts`。

## UI 设计与一致性

新增或修改界面前阅读并遵循 [UI 设计规范](docs/UI_DESIGN_SPEC.md)。复用共用主题变量、导航、面板标题及已有业务组件。通用视觉值集中维护，页面仅定义局部布局。页面族例外须按规范登记，UI 变更按规范清单审查。未实际执行的视觉检查标为待验收。日常界面改动优先在 5173 通过 Vite HMR 查看。

## 测试规范

开发阶段不主动运行测试和验收。持续集成在推送分支或正式版本标签后使用合成数据执行。启动健康和功能验收分别记录。用户明确安排本机测试或验收时使用以下命令。

- 后端：`python -m pytest -q`；测试文件命名为 `tests/test_*.py`。
- Python 检查：`python -m ruff check src tests scripts` 与 `python -m ruff format --check src tests scripts`。
- 前端：在 `frontend/` 执行 `npm run typecheck`、`npm run lint`、`npm test`（Vitest）；浏览器测试使用 `npm run test:browser`（Playwright），先构建并安装 Chromium。

默认离线测试禁止外部 HTTP。`live`、`postgres`、`identity` 标记区分真实服务、隔离数据库与身份边界；数据库验收使用专用库。旧业务替身测试不证明生产身份隔离通过。当前未配置数值覆盖率门槛。证据存入 `docs/test-records/v<版本>/<类型>/<UTC时间>/`，保留失败和跳过项，不覆盖历史。

## 提交与合并请求

日常开发不自动 Commit、Push、合并、打发布标签、创建 Release 或部署云端。只有在用户明确批准指定 `vX.Y.Z` 后，才按[发布手册](docs/DEVELOPMENT_AND_RELEASE.md#4-一次授权的正式发布)提交批准的文件范围、推送到 main 并为已核对的提交创建版本标签。GCP 直连 SSH 发布使用普通附注标签。受限 IAP 部署遵循其专用签名规则。该批准覆盖此版本正常的 CI、GHCR 推送和生产更新，无需在 CI 后另行批准。数据库迁移、破坏性操作、重大权限变更或密钥调整须按影响另获授权。Agent 的日常凭据与生产服务器的部署凭据分开保管。

历史提交使用简短、祈使式英文主题，例如 `Fix missing PNG validation in workflow archives`；沿用该风格，无须添加 Conventional Commits 前缀。保持提交范围集中，保留工作区已有修改。

合并请求应说明问题、行为变化、验证结果及限制，关联相关 issue；界面变更附截图，契约或部署变更同步文档。未执行的检查须明确标注。

## 配置与数据保护

密钥、ADS token、数据库凭据和邮件配置仅保存在服务端私有配置中；`VITE_*` 变量会暴露给浏览器。运行时使用 PostgreSQL/pgvector，不新增 SQLite 回退。开发脚本只允许在已核对的独立全新开发库初始化身份表。日常或生产数据库的初始化、迁移、清空和恢复必须获得明确授权。测试使用专用合成数据、空数据库和独立执行器。

维持科研查询的来源标注、现有单位约定、结果可复现性与按账号隔离。数值回归应明确物理假设、单位和误差阈值，保留运行所用镜像及相关科学工具版本。
