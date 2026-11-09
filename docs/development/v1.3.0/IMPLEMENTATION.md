# V1.3 绘图开发记录

2026-11-09 验收补充：协议2镜像在容器退出前流式返回输出，修复协议1中 tmpfs 随容器退出卸载导致产物丢失的问题；两种镜像增加中文字体。协议1镜像与本版不兼容，须重新构建两个 Dockerfile 并在本地配置中固定其新 SHA256。原部署记录保留协议1时的实际信息。测试范围与限制见[验收记录](../../test-records/v1.3.0/acceptance/20261109T003436Z/README.md)。

后续状态：2026-11-09 已按用户授权完成本机容器环境部署，见 [部署记录](DEPLOYMENT_2026-11-09.md)。下文2026-11-08的环境描述保留为当次开发记录。

2026-11-08。源码版本 `1.3.0.dev0` / 前端 `1.3.0-dev.0`，基线 `cc00e3b`。
本轮没有运行测试、构建、类型检查、浏览器验收、真实模型调用或数据库初始化；没有发布。
本地仅发现 v1.0.0、v1.1.0 标签，未据此推断远程 V1.2 状态。

## 本轮实现的源码

- 项目导航新增「数据绘图」。左侧选择数据与历史，中间查看来源、列与方案/脚本，右侧预览实际 PNG、放大及下载。
- UTF-8 CSV/TSV：5 MiB、10000 行、64 列，严格完整解析。长整数和 ID 列作为标识符，单元格原字符串保留；不自动猜单位、筛选、补值或更改本机原文件。
- 项目完整 Gaia 结果快照导入，读取 API 的全部 `data`，不使用模型可见的前十行。原始快照 JSON 与规范化 CSV 分别保存并记录 SHA256。
- 向模型发送前显示确切范围：列/类型/缺失数/已知单位/行数/前三行（每格最多120字符）。只有用户勾选确认并点击生成才发送；不发送原文件与路径。
- `plot_python` / `plot_gnuplot` 是独立方案工具。一次模型请求、最多一次工具调用，生成实际 `.py` / `.plt`，不是 Notebook 或 Gnuplot 的 Python 包装。
- 自动/指定引擎、散点/折线/直方图/误差棒的方案契约。列名与引擎一致性校验；图种、坐标轴、筛选、缺失值处理、实际科学正确性仍需验收。
- 方案与执行分开确认。UI 展示模型实际代码；只有已完成的本机方案可执行。导入的代码只读，须重新生成并审阅后执行。
- 数据集 UUID、方案 UUID、运行 UUID 幂等；同编号不同请求返回冲突。浏览器仅保留待确认请求，不自动重试；重启将运行中记录标为 interrupted，不重放收费请求。
- 一次最多一个绘图执行，复用原有两槽模型任务上限。模型 token 用量按上游返回保存，金额不猜测。
- 保存 PNG/PDF、真实脚本、CSV、原始输入、README、manifest；逐文件 SHA256、引擎镜像 ID/版本、资源边界、模型用量及来源与科学限制。单文件和 ZIP 使用同一份数据库字节。
- 项目归档格式 6 新增 `plotting.json`，读旧格式 1–5；含绘图数据的项目拒绝导出旧格式。导入全包校验、原子恢复及 ID 重映射，不执行脚本。归档来源数据仍需按私人科研材料保管，知识库的 metadata 选项不会移除绘图输入。

## 数据库准备边界

核心 schema 保持 6。新增绘图扩展版本 1，表为 `plot_meta`、`plot_datasets`、`plot_operations`、`plot_outputs`。
仅在网页「准备绘图数据库」弹框确认，或显式 `POST /api/v1/setup/plotting` 时创建；启动不会创建或迁移这些表。
绘图内容和运行中预留计入既有256 MiB业务预算；每个项目最多30个数据集、100条方案/运行记录。
项目删除沿用 FK 级联，生成/运行期间阻止删除。导入含绘图的归档前，也要先准备扩展表。

## 隔离执行配置

本轮只发现命令路径内没有 Docker / Gnuplot，未安装它们，也未执行容器。执行默认关闭，页面显示未配置；生成和下载方案不依赖执行环境。
服务器仅接受本机 Docker 的 Linux daemon（Windows Docker Desktop Linux 容器也须单独验收）；不接受 TCP/SSH 远程 daemon，不上传数据到远程容器服务。

在用户安排环境准备/验收时，将 Docker 程序、Linux 虚拟磁盘与镜像数据全部配置在 D 盘。先审阅 `containers/plotting/`，再显式构建两份镜像：

```powershell
docker build -f containers/plotting/python.Dockerfile -t astroagent-plot-python:1.3 containers/plotting
docker build -f containers/plotting/gnuplot.Dockerfile -t astroagent-plot-gnuplot:1.3 containers/plotting
docker image inspect --format '{{.Id}}' astroagent-plot-python:1.3
docker image inspect --format '{{.Id}}' astroagent-plot-gnuplot:1.3
```

构建结果尚未复现验证。基础镜像目前按 Python 3.12 / Debian bookworm 系列取用；运行必须固定本机构建结果的完整 SHA256 ID，不使用可变 tag，也不在执行请求中 pull。Python 镜像内固定 numpy 2.2.6、matplotlib 3.10.3；Gnuplot 镜像使用独立 `gnuplot-nox` 与实际版本记录。中文字体未随镜像准备，复杂中文标注的字形需验收和补充字体镜像。

服务端 `.env` 可配置以下非秘密字段，填入真实镜像 ID 后重启：

```dotenv
ASTROAGENT_PLOT_EXECUTION_ENABLED=true
ASTROAGENT_PLOT_PYTHON_IMAGE=sha256:<本机Python镜像的64位摘要>
ASTROAGENT_PLOT_GNUPLOT_IMAGE=sha256:<本机Gnuplot镜像的64位摘要>
ASTROAGENT_PLOT_TIMEOUT_SECONDS=30
```

镜像摘要必须匹配格式且标签声明绘图协议版本。服务启动时仅清理此前持久化为 running 的确切绘图容器名称；无 Docker 时保留中断记录，不枚举或删除用户其他容器。

执行前核对 daemon 的 Linux/seccomp/资源控制能力、镜像与容器设置。容器：无网络、只读根目录、非特权用户、drop ALL capabilities、no-new-privileges、1 CPU、256 MiB且不启用额外交换、32 PID、64 FD、单文件8 MiB、/output 20 MiB和/tmp 8 MiB tmpfs。唯一主机挂载是该次专用输入目录，只读；不挂载应用、凭据、HOME、Docker socket或输出目录。主机 CLI 环境不继承模型/数据库密钥。

可信容器入口分别调用 Python 或 Gnuplot，内部28秒截止，外部至多30秒等待；退出后强制删除容器。脚本输出只取固定文件，拒绝 tar 符号链接/硬链接/非常规成员，PNG最长边2400像素，未完整生成 PNG/PDF 时不交付半图。容器运行日志为有界数据，失败详情可在运行环境记录中查看。完整隔离、退出清理、平台差异仍待实际验收；没有语言 AST 过滤代替操作系统隔离，也没有宿主机执行回退。

Docker 执行和资源参数依据：[运行容器](https://docs.docker.com/engine/containers/run/)、[资源约束](https://docs.docker.com/engine/containers/resource_constraints/)。

## 新接口

- `GET /api/v1/setup/plotting`：存储/执行配置状态，不启动容器。
- `POST /api/v1/setup/plotting`：`confirm_create_tables:true`，显式建扩展表。
- 项目根 `/api/v1/projects/{project_id}/plotting`：数据集与方案/运行记录。
- `PUT .../datasets/{dataset_id}/upload`：单文件 multipart；`PUT .../datasets/{dataset_id}/snapshot`：快照/查询序号。
- `GET .../datasets/{dataset_id}/preview`：实际模型可见范围；`GET .../data.csv`：完整规范化数据。
- `PUT .../plans/{plan_id}`：数据集、allowlist 模型、需求、引擎、确认外发；`PUT .../runs/{run_id}`：已审阅方案和执行确认。
- `GET .../operations/{operation_id}`：状态；`GET .../runs/{run_id}/files/{name}`：固定文件名白名单；`POST .../runs/{run_id}/bundle`：所选白名单成员。

接口保留本机 Host / Origin、防压缩、实际请求体上限与错误脱敏；上传最多5 MiB加64 KiB multipart开销，绘图JSON沿用32 KiB上限。以生成的 OpenAPI / TypeScript 类型为字段准绳。

## 待验收

M1–M3 源码已接入；2026-11-09容器环境部署已完成，M2的实际绘图执行和M4验收尚未开展。没有声称模型调用、四种图、Gnuplot绘图、完整隔离或浏览器功能已通过。
验收样本与门槛沿用 [版本计划](../../PROJECT_PLAN_V1.3.md)；既有固定 Gaia 图、RAG、会话、附件、归档仍需兼容验收。版本未发布，不能复用 V1.1 的通过记录。
