# AstroAgent 开发与发布手册

## 1. 三套环境

| 环境 | 运行位置 | 数据与入口 | 更新方式 |
| --- | --- | --- | --- |
| Development | Windows Docker Desktop 的 WSL2 Linux 引擎，默认使用 Compose 项目 `astroagent-v16` | 原有账号与科研数据，浏览器 [本机入口](http://127.0.0.1:5173) | 每轮构建并更新有改动的服务 |
| Testing | GitHub Actions 托管 Linux Runner | 临时 PostgreSQL／pgvector、合成身份和科研数据、独立绘图环境。Runner 结束后销毁 | 分支 Push，或指定签名版本的发布检查 |
| Production | GCP Linux 虚拟机，Compose 项目 `astroagent-gcp` | 固定 HTTPS 地址、PostgreSQL／pgvector 持久卷、用户和科研数据 | 保护标签、通过 CI 的镜像摘要、受限 IAP SSH 命令 |

本机站点经同源代理访问 FastAPI。认证、CSRF、MFA、按账号数据边界沿用应用实现。SIMBAD、Gaia、ADS、LangChain 模型客户端、RAG、脚本绘图及计算队列继续使用仓库现有组件。涉及数据库试验或正式业务验收时，使用独立环境与专用数据。

## 2. 本机启动、更新和预览

### 默认使用 5173 并按轮更新

在 Docker Desktop 中使用 Linux 容器和 WSL2 后端。已有部署直接启动 `astroagent-v16`，从 [5173 本机入口](http://127.0.0.1:5173) 登录。该项目名沿用 V1.6 的名称和数据库卷。日常使用及迭代预览共用现有账号、会话和科研数据。

Agent 每轮完成应用源码或运行配置修改后，在仓库根目录执行对应服务的 PowerShell 更新命令。

```powershell
.\scripts\containers.ps1 -Action update -Service frontend
.\scripts\containers.ps1 -Action update -Service frontend,backend
.\scripts\containers.ps1 -Action update -Service frontend -CheckOnly
.\scripts\containers.ps1 -Action status
```

脚本核对本机项目、已挂载的数据库卷及账号数据库。镜像构建成功后替换指定服务，等待容器健康并检查登录入口与认证预检。检查通过后刷新 5173。已有容器停止时，脚本可启动现有核心依赖。后端或计算 Worker 替换前检查活动任务。数据库结构变更、身份或凭据调整以及真实数据操作按影响单独授权。

| 本轮改动 | 更新目标 |
| --- | --- |
| Vue、CSS、TypeScript、前端锁文件 | `frontend` |
| FastAPI、Python 依赖 | `backend` |
| API 契约及同步的前端类型 | `backend,frontend` |
| 本机入口代理 | `ingress` |
| 隔离绘图代理 | `plot-executor` |
| REBOUND 或 PeTar Worker | `compute-worker` |

### 按需启动隔离开发环境

需要隔离预览或在独立数据库中试验时，显式启动 `astroagent-dev`。隔离配置继续提供 Vite HMR 和 Uvicorn reload。

```powershell
.\scripts\dev.ps1 -Action Start
.\scripts\dev.ps1 -Action Status
.\scripts\dev.ps1 -Action Logs -Service backend
```

打开 [http://127.0.0.1:15273](http://127.0.0.1:15273)。首次启动只给识别到的空开发数据库安装身份表。脚本在 `.astroagent/dev/runtime.env` 创建开发专用随机凭据，以后沿用该文件。开发预览启用本机 HTTP，只有 Vite 端口映射到宿主机环回地址。开发默认关闭邮件注册和外部模型凭据。需要进入已登录页面时运行 `.\scripts\dev.ps1 -Action Account`，脚本在开发库创建一个合成账号并在本机显示登录信息。邮箱注册、找回密码及实际送达使用专用测试环境验证。

使用隔离环境时，执行 `.\scripts\dev.ps1 -Action Update` 核对资源和镜像。已绑定的源码由 Vite 或 Uvicorn 检测。打开的页面通常随 HMR 更新，后端重载结束后刷新页面或重试请求即可。

| 改动 | 容器处理 |
| --- | --- |
| Vue、CSS、TypeScript、HTML、Vite 配置 | 只读挂载，Vite 使用轮询处理 Windows 文件事件。HMR 无法保留的页面状态由 Vite 全页刷新 |
| FastAPI 的 Python 源码 | 只读挂载，Uvicorn 在开发容器重载。身份表和计算任务由独立卷保留 |
| Python、Node 依赖或 Dockerfile | 按锁文件、构建配置及镜像目标识别受影响服务，复用 Docker 层。可用 `-Rebuild frontend` 或 `-Rebuild backend` 重建指定服务 |
| 开发 Compose | 根据有效的服务配置更新容器。镜像构建参数发生变化时才按对应目标重建 |
| REBOUND、PeTar Worker | 启用时检查对应代码和依赖，发现活动任务则等它们结束后再更新。现有调度租约与尝试标识继续由应用管理 |
| Python、Gnuplot 绘图镜像或隔离执行器 | 增加命令 `.\scripts\dev.ps1 -Action BuildPlot -PlotImage python`，按改动可改为 `gnuplot`、`executor` 或传入多个明确目标 |
| PostgreSQL 架构 | 核对版本和目标数据。开发启动只做空库身份初始化，架构更新及恢复单独处理 |

模型和计算按需启用。复制 [.env.dev.example](../.env.dev.example) 为 `.env.dev`，填入已有模型目录及摘要。Embedding 和 Ollama 模型以只读方式共享，选用自己的模型时检查模型名与 V1.5 的本地助手契约。脚本不移动模型文件。启用计算前先启动基础服务，再设置 `ASTRO_DEV_COMPUTE=1`，执行 `.\scripts\dev.ps1 -Action InitCompute` 和 `.\scripts\dev.ps1 -Action Update`。隔离绘图的开发镜像可以单独构建。连接运行中的绘图代理需要独立可信边界，默认开发容器不上挂日常 Docker Socket。OCI 镜像与业务验收分别记录。

在隔离环境用 `Status`、`Logs` 或 `Stop` 查看、排查及暂停。停止保留开发卷、私有配置和模型。单独停一个服务可指定 `-Service`。预览端口冲突时先核对占用及项目归属。更新失败保留错误记录，向用户说明当前实际可用地址和影响范围。

## 3. Agent 规则加载与交接

根目录 [AGENTS.md](../AGENTS.md) 是唯一完整规则。客户端内置提示或规则读取依赖版本及打开的工作区。使用仓库根目录启动 Agent。只有能访问这台 Windows 电脑的 Agent 才能执行本机容器操作，云端 Agent 须由本地会话执行相同脚本。

| 工具 | 规则入口与检查 |
| --- | --- |
| Codex | 直接读取根 `AGENTS.md`。[Codex 项目说明](https://developers.openai.com/codex/guides/agents-md) |
| Claude Code | `CLAUDE.md` 通过 `@AGENTS.md` 导入。可在 `/memory` 确认。[Claude Code 规则加载](https://code.claude.com/docs/en/memory) |
| Gemini CLI | 默认 `GEMINI.md` 导入同目录文件。可在 `/memory show` 查看。若个人设置覆盖了上下文文件名，应保留 `GEMINI.md` 或直接加入 `AGENTS.md`。[Gemini CLI 项目上下文](https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html) |
| Google Antigravity | 当前项目规则支持根 `AGENTS.md`，可在 Agent 侧栏的 Rules 查看工作区规则。[Antigravity 规则](https://antigravity.google/docs/rules/) |
| Cursor | Agent 原生支持项目根 `AGENTS.md`，选用打开本机仓库的 Agent 会话。[Cursor 项目规则](https://cursor.com/docs/rules) |
| GitHub Copilot | 支持 Agent 指令的入口会读取 `AGENTS.md`。另提供 `.github/copilot-instructions.md` 指向共享规范，覆盖读取仓库通用指令的客户端。可在响应引用或相应诊断里检查实际加载文件。[Copilot 仓库指令](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions) |

每轮交付应记录改动文件、受影响服务、实际更新和服务状态、入口及待验证内容。仓库规则适用于 Agent 开发流程。GitHub 保护规则、签名、服务器权限和本机脚本的目标核对负责实际操作边界。

## 4. 一次授权的正式发布

日常开发可保留未提交修改。发布前由用户明确批准一个版本及改动范围。发布操作者复核现有修改、密钥及私有科研数据的排除规则，更新 Python、前端和前端锁文件里的版本号并提交，按保护规则将同一提交推送或合并到 `main`。记录最终位于 `main` 的完整提交 SHA。然后使用受限发布身份创建并推送签名标签。

```powershell
# 在获得该版本发布授权并核对实际 Commit SHA 后运行
$releaseVersion = 'vX.Y.Z'
$releaseCommit = '填写已批准的完整提交SHA'
$releaseKey = '填写发布签名密钥路径'
git -c gpg.format=ssh -c "user.signingkey=$releaseKey" tag -s $releaseVersion $releaseCommit -m "Release AstroAgent $releaseVersion"
git push origin "refs/tags/$releaseVersion"
```

签名密钥在日常 Agent 会话外保管，可使用单独的发布身份或支持用户在场的 SSH 签名设备。聊天中的“发布 vX.Y.Z”授权提交和该次签名操作。GitHub 以该签名标签识别批准的版本及 SHA。普通 Git 凭据不得持有标签规则的绕过权限或发布签名密钥。用户只在发起该版本发布时授权一次，CI 成功后流程自动推进。修改已签名提交或换版本需要新的明确授权。

`test.yml` 由分支推送触发，发布工作流也对签名标签的提交调用同一套 CI。必要检查包含 Ruff、离线 Python 测试、PostgreSQL 真实身份、RAG、N 体队列及隔离绘图、前端类型／Lint／Vitest／构建、OpenAPI 和现有 Playwright 用例，以及 Python 和 npm 依赖审计与容器镜像构建。PostgreSQL JUnit 门槛要求关键测试模块实际执行且无跳过项。仅适用于真实上游、Windows 或额外数据的用例按条件保留状态。科学 CI 使用两颗各 0.5 太阳质量、分离 1 AU 的孤立圆轨道双体，以 1 yr 为周期分别运行实际 REBOUND 和 PeTar，可执行误差阈值见脚本。全部必要门槛通过后才构建正式镜像。

`release.yml` 发布前端、后端、Caddy、PostgreSQL 初始化镜像、计算 Worker 和三种绘图相关镜像到 GHCR。用 `vX.Y.Z` 与 `sha-<完整提交>` 标记，每个版本报告列出实际 `@sha256:…` 摘要。镜像按构建输入和服务使用独立缓存，未变化的镜像可复用。PeTar 编译层与后端安装层可共享。源文件依赖确有变化时才需新的对应构建输入。版本标签冲突直接失败。无 `latest` 生产依赖。部署报告中的版本表示发布提交，复用镜像的 `org.opencontainers.image.revision` 对应其首次构建提交。

## 5. GitHub 与 GCP 的一次性启用

### GitHub

1. 为 `main` 配置保护，包含必要 CI 状态、禁止强推，保护工作流及部署脚本改动的审查。为正式 `v*.*.*` 标签设置规则集，限制创建、更新、删除，仅受控发布身份可创建。普通 Agent 凭据排除在绕过名单外。发布后保持原标签与摘要，修复使用新版本。
2. 在 Actions 仓库变量设置 `RELEASE_SIGNING_PUBLIC_KEY`，填发布签名的 OpenSSH 公钥类型及公钥值，去掉结尾备注。使用 `ssh-ed25519` 或 `sk-ssh-ed25519@openssh.com`。启用前保持 `PRODUCTION_DEPLOY_ENABLED` 未设置或 `false`。
3. 创建 GitHub Environment `release-registry` 和 `production`，均只允许 `v*.*.*` 的标签，取消分支通配和额外人工 Review。按下表设置变量与 Secrets。GCP 端独立校验签名标签和带来源证明的清单。
4. 为 GHCR 包关闭从仓库继承的权限，使用包的独立权限管理。把写权限留给受限的镜像发布身份，普通分支的 `GITHUB_TOKEN` 在包上最多有读权限。这样用于复用的输入标签和缓存只能由正式发布更新。镜像通过自定义标签记录源码，保留包的独立权限。生产拉取私有镜像只需读取权限。[GHCR 包权限](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility)

| 类型 | 名称 | 值 |
| --- | --- | --- |
| `release-registry` 变量 | `GHCR_PUBLISH_USER` | 具备目标包推送权限的 GitHub 账号 |
| `release-registry` Secret | `GHCR_PUBLISH_TOKEN` | 仅用于目标 GHCR 包的经典个人访问令牌，权限 `write:packages`，避免授予 `repo` 或删除权限 |
| Environment 变量 | `GCP_PROJECT_ID`、`GCP_ZONE`、`GCP_VM` | 唯一目标的 GCP Project ID、可用区和虚拟机实例名称 |
| Environment 变量 | `GCP_WORKLOAD_IDENTITY_PROVIDER`、`GCP_DEPLOY_SERVICE_ACCOUNT` | WIF Provider 完整资源名、部署服务账号邮箱 |
| Environment Secret | `GCP_DEPLOY_SSH_KEY` | 限定只执行部署命令的 SSH 私钥，与 Git 签名密钥分开 |
| Environment Secret | `GCP_DEPLOY_KNOWN_HOST` | `astroagent-production ssh-ed25519 <主机公钥>`，从 GCP 管理终端核对后填写 |

可先让签名版本产出 CI、镜像和清单。生产前确认当前 GitHub 方案支持仓库的标签规则、Environment 和 artifact attestations。若缺少可靠的标签或证明保护，保持自动部署关闭，在受控环境使用已批准源码和经核对的摘要安排人工部署。避免把普通仓库写权限当作发布批准。[GitHub 标签规则](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets) · [GitHub 部署环境](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments) · [来源证明可用性](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)

### GCP 虚拟机

1. 按 [GCP 手册](../containers/gcp/README.md) 让经授权的维护者准备 Docker Compose、HTTPS、Gemini／邮件、私有 `.env`、业务卷和备份。完成已批准的首装或迁移，确认运行基线的标签、SHA 及数据兼容性。常规自动更新从这个健康基线开始，不执行首装、迁移或恢复。
2. 为 GitHub Actions 配置独立 WIF Provider。以 GitHub 不变的仓库 ID、`assertion.ref_type == 'tag'`、`assertion.environment == 'production'` 和指向本仓库 `.github/workflows/release.yml@refs/tags/` 的 `assertion.workflow_ref` 前缀限制令牌。仅允许模拟上述部署服务账号。给它 IAP 到指定实例、端口 22 的权限，以及 `compute.instances.get` 和 `compute.instances.list`。虚拟机的 22 端口仅放行 IAP 所需范围，80／443 继续提供网页。IAP 的传输权限和 SSH 的公钥认证分别配置，无需公开 SSH 或上传 GCP 服务账号私钥。[Google WIF Action](https://github.com/google-github-actions/auth) · [GitHub OIDC 声明](https://docs.github.com/en/actions/reference/security/oidc) · [GCP IAP 权限与防火墙](https://docs.cloud.google.com/iap/docs/using-tcp-forwarding)
3. 安装支持 `gh attestation verify` 的 GitHub CLI，使用可读取本仓库证明的凭据登录。私有仓库的 Git、GitHub 证明和 GHCR 读取凭据分别配在服务器 root 的受控配置中。脚本使用 `/etc/astroagent/gitconfig`、`/etc/astroagent/gh` 和 `/etc/astroagent/docker`。公开源码和公开镜像无需提供仓库写凭据。
4. 从已审阅的仓库副本安装下列文件。部署账户无 Docker 组权限。用 `ssh-keygen` 从系统的真实主机公钥核对指纹，避免接受 runner 运行时临时扫描的主机密钥。服务器的发布公钥与 GitHub 签名公钥一致。

```bash
# 已批准设置生产服务器时，在已审阅的源码目录执行
sudo install -d -m 0755 /usr/local/lib/astroagent /etc/ssh/authorized_keys /var/empty
sudo install -d -m 0700 /etc/astroagent /var/lib/astroagent-release
sudo install -m 0644 scripts/release_assets.py containers/gcp/release_apply.py /usr/local/lib/astroagent/
sudo install -m 0755 containers/gcp/release-ssh.sh /usr/local/sbin/astroagent-release-ssh
# 仅首次安装设置文件，后续保留站点原配置
sudo install -m 0600 containers/gcp/release-settings.example.json /etc/astroagent/release.json
sudo useradd --system --no-create-home --home-dir /var/empty --shell /bin/sh astroagent-release
sudoedit /etc/ssh/authorized_keys/astroagent-release
sudoedit /etc/astroagent/release-signers
sudo visudo -cf containers/gcp/release.sudoers
sudo install -m 0440 containers/gcp/release.sudoers /etc/sudoers.d/astroagent-release
sudo install -m 0644 containers/gcp/release.sshd.conf /etc/ssh/sshd_config.d/90-astroagent-release.conf
sudo sshd -t
sudo systemctl reload ssh
```

`authorized_keys` 放 IAP 部署用的公钥，文件由 root 管理且允许 SSH 进程读取。`release-signers` 使用 `astroagent-release namespaces="git" <正式发布签名公钥>`。安装测试时保持既有 SSH 会话，核对目标机的 SSH 服务和部署账户条件。系统环境已启用 OS Login 时，先核对本地受限账户及 `AuthorizedKeysFile` 能否被系统策略使用。

将 `/etc/astroagent/release.json` 指向真实的 root 管理 Compose 目录，`compute` 和 `rag` 必须匹配现有站点。Compose 文件、启动验证脚本与 `.env` 一起固定为当前经审阅的部署契约。目录祖先及文件应由 root 控制，`.env` 权限为 `0600`。首次登记运行基线时，用实际已经部署并核对的版本标签和 SHA 替换命令参数。

```bash
sudo /usr/bin/python3 -I /usr/local/lib/astroagent/release_apply.py adopt vX.Y.Z '填写已部署的完整提交SHA'
sudo /usr/bin/python3 -I /usr/local/lib/astroagent/release_apply.py status
```

确认隔离环境下的部署和恢复演练后，将服务器设置 `enabled` 改为 `true`，再设置仓库变量 `PRODUCTION_DEPLOY_ENABLED=true`。签名版本的 CI、GHCR 清单和证明完成后，工作流通过 IAP 调用服务器。服务器再次核对签名标签、版本与 SHA、生产 Compose、已运行镜像及清单的 GitHub 证明，按摘要拉取镜像。它只更新镜像实际变化的应用服务，保留数据库服务和持久卷。PostgreSQL 及隔离绘图的部署配置有变更时走维护流程。生产配置保持 HTTPS、无源码挂载和无开发重载。整个流程按发布串行，服务器额外持互斥锁。

## 6. 失败、停止、回退与核对

- CI 失败时，在 Actions 查看真实失败及跳过报告。还未签名的修改继续走开发流程。修正已经打标签的源码使用新版本和新签名。遇到可恢复网络问题、队列忙或 GitHub 服务故障，可对同一受权标签重跑失败的作业。
- 生产目标、签名、SHA、提出的镜像摘要或生产文件不匹配时，在更新前停止。检测到架构、认证边界、生产 Compose 变化或新增架构语句时安排单独审查。数据库兼容性还需以项目约定及验收证据确认。
- 服务更新后检查 Docker 健康、HTTPS 登录页、认证预检、匿名业务拦截和探针隔离。失败记录包含目标、原镜像及改动服务。`pending.json` 保留于部署状态目录，未核对状态前不继续其它版本。操作员先查现状、之前的镜像和备份，再决定恢复方案。
- 代码提供上一组已验证应用摘要的回退路径，`auto_rollback` 默认关闭，待独立环境证明同库兼容、原镜像可用及恢复后的健康检查后再启用。数据库恢复、清理及涉及真实数据的回滚由用户另行批准。保持备份、账户、模型、队列及科研产物所在卷。
- 临停自动部署时将仓库变量 `PRODUCTION_DEPLOY_ENABLED` 和服务器 `enabled` 关闭。已开始的更新先查看 Actions 与服务器状态，核对是否存在待处理记录。必要时通过撤下部署专用 SSH 公钥或 GCP IAP 授权暂停新连接。
- 使用服务器的 `status` 核对实际运行的容器、当前版本及完整提交。Actions 归档 CI 结果、`release.json` 和部署日志。进入服务更新阶段后，服务器另存 JSON 报告于 `/var/lib/astroagent-release`。同目录的 `images.json` 保留 Compose 使用的镜像摘要覆盖，手工维护时以已记录并核对的摘要为准。成功后 GitHub Release 附清单与报告。启用前的镜像产出记录显示生产作业跳过。

## 7. 当前交付状态

本机日常使用与改动预览已统一到 `astroagent-v16`。按轮更新预检已核对 5173、原数据库卷及五个可选更新目标。撤下旧隔离预览容器前后，5173 的登录页和认证预检均成功，原数据卷和隔离开发卷均保留。隔离预览配置仍可按需使用。

GitHub 端的权限、Secrets、GHCR 包权限、GCP IAP、目标实例、签名公钥、生产基线和数据备份由首次启用时配置。正式 CI、各客户端规则加载及业务验收、远程部署和自动回退演练另行记录。

## 8. 本次文件清单

| 范围 | 文件 |
| --- | --- |
| 本机及隔离开发 | [containers.ps1](../scripts/containers.ps1)、[compose.dev.yaml](../compose.dev.yaml)、[.env.dev.example](../.env.dev.example)、[.gitignore](../.gitignore)、[dev.ps1](../scripts/dev.ps1)、[dev_identity.py](../scripts/dev_identity.py)、[开发数据库 SQL](../containers/dev/10-database.sql) |
| 服务与构建 | [Vite 配置](../frontend/vite.config.ts)、[前端 Dockerfile](../containers/frontend/Dockerfile)、[Python 绘图 Dockerfile](../containers/plotting/python.Dockerfile)、[Gnuplot Dockerfile](../containers/plotting/gnuplot.Dockerfile)、[Bake 镜像定义](../containers/release/docker-bake.hcl) |
| Agent | [AGENTS.md](../AGENTS.md)、[CLAUDE.md](../CLAUDE.md)、[GEMINI.md](../GEMINI.md)、[Copilot 指令](../.github/copilot-instructions.md) |
| CI 与发布 | [test.yml](../.github/workflows/test.yml)、[release.yml](../.github/workflows/release.yml)、[CI 核对脚本](../scripts/ci_verify.py)、[镜像清单脚本](../scripts/release_assets.py) |
| GCP | [服务器更新脚本](../containers/gcp/release_apply.py)、[服务器配置模板](../containers/gcp/release-settings.example.json)、[SSH 入口](../containers/gcp/release-ssh.sh)、[sshd 配置](../containers/gcp/release.sshd.conf)、[sudoers 规则](../containers/gcp/release.sudoers) |
| 文档 | 本手册、[README](../README.md)、[V2.0 开发文档](PROJECT_PLAN_V2.0.md) |
