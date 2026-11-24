# Siderfolio 在 GCP 上的生产部署

适用于新加坡区域的 Ubuntu 24.04 x86_64、`n2-standard-2`（2 vCPU、8 GiB）及 80 GB 磁盘。方案沿用仓库的 Vue 和 FastAPI 镜像构建，新增 Caddy 与 PostgreSQL 初始化镜像。Caddy 是对外入口，网页与 API 使用同一个站点地址。后端直接访问 Gemini 和天文服务，无需 HTTP 或 SOCKS 代理。 [Compute Engine N2 规格](https://docs.cloud.google.com/compute/docs/general-purpose-machines)

```text
浏览器 → Caddy :80 / :443 → Vue 静态服务及同源 API 代理 → FastAPI
                                                            ├→ PostgreSQL + pgvector
                                                            └→ Gemini / SIMBAD / ADS / Gaia
可选 N 体 Worker 通过专用卷与 FastAPI 交换任务，容器无网络。
```

## 1. 选择公网入口

| 模式 | 在 `.env` 里填写 | 浏览器访问 |
| --- | --- | --- |
| 有域名 | `SITE_MODE=domain`，`PUBLIC_HOST` 填已解析到虚拟机的域名 | Caddy 自动签发和续期域名 HTTPS 证书，80 端口跳转到 HTTPS |
| 暂无域名 | `SITE_MODE=ip`，`PUBLIC_HOST` 填该虚拟机的真实公网 IPv4 | 可直接输入 `http://公网IP`，80 端口接入后跳转至同一 IP 的 HTTPS。Caddy 2.11 及以上通过 Let's Encrypt `shortlived` 配置签发和续期 IP 证书 |

Siderfolio 的登录和邮件链接要求固定的 HTTPS 站点。公网 IP 模式同样使用 HTTPS 登录。保留现有的 80／443 TCP 防火墙放行，核对规则确实应用到目标实例。IP 模式建议先将当前外部 IP 保留成静态地址。域名模式把 A 记录指向服务器，只有在服务器配置对应公网 IPv6 时才保留 AAAA 记录。Caddy 的证书账户和续期数据保存在专用卷。 [GCP 保留静态外部 IP](https://docs.cloud.google.com/compute/docs/ip-addresses/configure-static-external-ip-address) · [Let's Encrypt IP 证书](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability) · [Caddy TLS 参数](https://caddyserver.com/docs/caddyfile/directives/tls)

## 2. 从克隆到启动

服务器需要 Docker Compose 插件、Docker BuildKit、Git、Bash、Python 3 和 curl。部署命令在具有该服务器 Docker 操作权限的 SSH 账号下执行。确认 80 和 443 当前没有被别的 Web 服务占用。

开发期间，将本次构建对应的源码包上传到站点目录并解压。正式发布后可以检出对应版本的源码。两种方式均保留 `containers/gcp/.env`、应用目录和 Docker 数据卷。使用有 Docker 权限的账号执行以下命令。服务器仅允许通过 sudo 操作 Docker 时，为部署命令加 `sudo`。

```bash
bash containers/gcp/deploy.sh prepare
vi containers/gcp/.env
bash containers/gcp/deploy.sh deploy --init-db
```

`--init-db` 用于已确认新建且获准初始化的空库。已有部署更新使用 `deploy`。

在编辑器里填写下面几项并保存：

- `SITE_MODE` 和 `PUBLIC_HOST`。证书联系邮箱 `ACME_EMAIL` 可按需填写。`PUBLIC_HOST` 只写主机名或公网 IPv4，不写 `https://` 或端口。
- `GEMINI_API_KEY` 和 `GEMINI_MODEL`。选择 Google 项目中可用的文本生成模型。底层复用项目的 Gemini 协议，Compose 将密钥和模型 ID 映射到既有后端配置变量。此处使用 Gemini Developer API，Vertex AI 服务账号认证是另一种配置。 [Gemini 模型](https://ai.google.dev/gemini-api/docs/models) · [项目模型服务商说明](../../docs/development/v1.6.0/MODEL_PROVIDERS.md)
- `SMTP_HOST`、`SMTP_PORT`、`SMTP_MODE`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM`。首次注册及密码重置依赖已授权的发件服务，使用供应商指定的 TLS 465 或 STARTTLS 587。 [GCP 发信端口](https://docs.cloud.google.com/compute/docs/tutorials/sending-mail)
- 如需 ADS 文献检索，填写 `ADS_API_TOKEN`。SIMBAD 和 Gaia 使用既有公开查询路径。部署脚本会生成两套数据库密码、内部代理凭据和身份加密密钥，更新时沿用原值。

`deploy.sh` 校验模板、串行构建镜像、校验 Caddy 配置，启动 PostgreSQL 后在明确指定 `--init-db` 时安装身份表，再等待容器和 HTTPS 就绪。它检查 80 端口跳转 `308`、HTTPS 登录页和认证接口 `200`、匿名业务请求 `401`、公网内部探针 `404`。验证使用真实主机名或 IP 检查证书，同时连接本机发布端口，避免从 VM 回连其公网 NAT。首次部署后再从你自己的浏览器打开公网地址，确认 GCP 入站访问。Gemini 推理和邮箱实际送达需要各自实测。

`.env` 权限为 `0600`，已有的仓库 `.gitignore` 忽略它，镜像构建上下文也排除它。Gemini 密钥只进入后端环境，数据库密码只进入 PostgreSQL 和需要连接它的后端。可用 `compose config --quiet` 校验，不要分享展开后的 Compose 配置或 Docker 环境变量列表。拥有服务器 Docker 控制权的用户可以读取容器环境。日志为 `json-file`，每个长期运行的容器 `restart: unless-stopped`，每个日志文件 `max-size: "50m"`，最多 3 个。数据库和执行器端口不发布到公网。

### 以 www 作为正式站点

域名接入时，在 DNS 中将根域名的 A 记录指向当前服务器的固定公网 IPv4，将 `www` 的 CNAME 指向根域名。Cloudflare 记录使用仅 DNS 和自动 TTL。服务器只配置 IPv4 时保留 A 与 CNAME。域名切换属于生产维护，先核对当前版本、备份、容器和发布方式，经批准后仅更新站点相关配置。

```dotenv
SITE_MODE=domain
PUBLIC_HOST=www.siderfolio.com
APEX_REDIRECT_HOST=siderfolio.com
```

`APEX_REDIRECT_HOST` 可留空。启用时须填写 `PUBLIC_HOST` 对应的根域名。Caddy 为两个名字分别管理受信任的 HTTPS 证书。根域名的 HTTP 和 HTTPS 都直接返回 `308` 到 `https://www.siderfolio.com`，保留路径和查询参数。站点的 Cookie、认证来源、前端 API 和新邮件链接均使用 www。由 IP 版切换后，用户首次打开 www 时需在原有账号下重新登录；旧邮件若仍指向 IP，可在 www 重新申请相应链接。

部署后的 `verify` 会核对两个域名的证书、重定向目标和认证入口。直连 SSH 发布保留已启用的本地命名模型和现有的内部模型网络。使用 IAP 受控发布时，域名和 Compose 变更需走维护流程，核对实际运行的新版本后通过部署工具登记运行基线。 [生产发布与维护流程](../../docs/DEVELOPMENT_AND_RELEASE.md#5-github-与-gcp-的一次性启用)

## 3. 首次登录与业务验证

从 HTTPS 的 `/register` 注册，收邮件、激活并设密码，再登录。用一条无需附件的简单聊天验证 Gemini，用 ADS token 配置完成后再验证文献检索。这些动作独立于启动探针。

需要管理员时，先在站点完成注册激活。以下在 SSH 中设定 `ADMIN_EMAIL` 为你刚激活的账号，停后端释放本地维护锁，先预览再明确确认提升，最后恢复服务。登录后完成 MFA，随后访问 `/admin`。 [现有首位管理员流程](../../docs/development/v1.6.0/OPERATIONS.md#3-初始化首位管理员)

```bash
read -r -p '已激活的管理员邮箱：' ADMIN_EMAIL
bash containers/gcp/deploy.sh compose stop backend
bash containers/gcp/deploy.sh compose run --rm --no-deps backend -m astroagent.identity_cli bootstrap-admin --email "$ADMIN_EMAIL"
bash containers/gcp/deploy.sh compose run --rm --no-deps backend -m astroagent.identity_cli bootstrap-admin --email "$ADMIN_EMAIL" --apply
bash containers/gcp/deploy.sh compose up -d --wait backend
unset ADMIN_EMAIL
```

如果你在站内保存过自定义模型目录，目录会优先于启动环境。更新 `.env` 后按部署命令重建容器配置，已保存的模型服务商凭据另在管理员设置中更新。稳定使用环境配置前，核对实际选中的服务商和模型。

## 4. 单机资源与功能开关

默认启动 PostgreSQL、后端、前端、Caddy。后端最多 3 GiB 和 1.5 vCPU，数据库最多 1,280 MiB，前端和 Caddy 各 256 MiB。容器 CPU 限制为上限，叠加值不代表可同时获得这些算力。首装构建串行进行，给 2 vCPU 的主机留出系统和容器运行空间。该规格优先用于 Gemini 聊天、天文查询与知识库基础功能，观察磁盘、内存和上游限额后再扩大并发。文献管理与追踪能力以你部署的源码版本为准。

- **N 体计算。** 将 `.env` 中 `COMPUTE_ENABLED=1`。首装使用 `bash containers/gcp/deploy.sh deploy --init-db --init-compute`，已装站点首次开启时使用 `bash containers/gcp/deploy.sh deploy --init-compute`。脚本以应用数据库角色显式安装增量计算表，启动无网络的 1 vCPU／512 MiB Worker，使用仓库本版的 REBOUND／PeTar 镜像。常规更新使用 `deploy`。排空活跃任务后再停用 Worker。 [计算任务运维说明](../../docs/development/v1.7.0/OPERATIONS.md)
- **语义 RAG。** 基础部署保留本地知识库的词法检索。准备仓库认可的本地嵌入模型与 SHA-256 后，在 `.env` 填写 `EMBEDDING_MODEL_DIR`、`EMBEDDING_MODEL_SHA256`，用 `bash containers/gcp/deploy.sh --rag deploy` 只读挂载模型。首装再加 `--init-db`。启用后部署及管理命令保留 `--rag`。没有 CPU 内存实测前先从小文档开始。 [固定嵌入模型准备说明](../../docs/development/v1.0.0/MODEL_SETUP.md)
- **Ollama 与脚本绘图。** 这台 VM 的基础配置使用云端 Gemini，Ollama 与模型权重不上机。网页中的程序生成脚本需通过专用绘图隔离环境执行，基础配置关闭该执行功能。需启用时按现有独立执行器契约配置并验收，通过内部网络连接；公网后端不挂 Docker 控制接口。 [绘图执行与隔离方案](../../docs/CONTAINER_DEPLOYMENT_V1.5.md)

## 5. 更新、备份与排查

日常升级先备份并核对目标源码版本和数据库兼容性，再执行 `bash containers/gcp/deploy.sh deploy`。该操作保留 Compose 项目名和已有卷。`.env` 中的 PostgreSQL 密码用于空卷初始化，修改它不能为现有数据库轮换密码。保留身份加密密钥，恢复后端配置时它用于解密原有身份和模型配置。不要因为首次启动或证书故障删除数据库卷。

```bash
bash containers/gcp/deploy.sh compose ps
bash containers/gcp/deploy.sh compose logs --tail=80 ingress backend postgres
bash containers/gcp/deploy.sh verify
```

证书迟迟未就绪时优先看 Caddy 日志，确认 DNS 或公网 IPv4、80／443 入站及服务器的 ACME 出站访问，证书签发成功后重跑 `verify`。登录页可访问但认证接口返回 `503` 时核对身份表和数据库密码；邮件能配置不等于已投递，需核对 SMTP 日志和收件结果。Gemini 认证、配额或结算问题应以该项目在 Google 的实际返回为准。

## 6. 账号用量与计算容量

`REGISTRATION_ENABLED` 控制新注册。已有账号仍可登录和找回密码，已有待激活账号可继续激活。管理员在 `/admin` 的用户行可查看并修改账号配额。默认值由 `MODEL_REQUESTS_PER_HOUR`、`ASTRONOMY_QUERIES_PER_HOUR`、`ACCOUNT_STORAGE_MIB` 和 `ACCOUNT_COMPUTE_QUEUED` 设置。

模型和天文查询按 UTC 自然小时记录实际请求尝试。已经启动的调用即使失败也计入，因为上游可能已处理。用原编号取回已受理结果时沿用原记录。存储按账号 PostgreSQL 表及索引的已分配空间计算，在会话及知识库写入入口检查。单机最多有 24 项计算排队，同时执行一项，运行与正在取消共用此执行槽。

## 7. 备份、恢复和回退

在维护窗口先等正在执行或取消的计算结束，再停止后端。用 `backup` 生成同一恢复点的 PostgreSQL 转储和持久文件归档，完成后使用原部署配置启动后端。

```bash
bash containers/gcp/deploy.sh compose stop backend
bash containers/gcp/deploy.sh backup /srv/siderfolio-backups
bash containers/gcp/deploy.sh compose up -d --wait backend
```

备份目录包含 `database.dump`、`application.tar` 和 `SHA256SUMS`。在成品目录运行 `sha256sum -c SHA256SUMS`。另行受控保存原部署的身份加密密钥与私有配置。计算交接卷及 Caddy 缓存可由目标环境重新建立。 [PostgreSQL 16 备份与恢复](https://www.postgresql.org/docs/16/backup-dump.html)

恢复需取得明确授权。为演练选用独立 Compose 项目及空卷，仅启动其数据库，使用相同版本的 PostgreSQL 与 pgvector。保留备份的身份加密密钥，配置独立的数据库密码和站点地址。在目标库预安装扩展后，从 `pg_restore --list` 的目录中排除扩展创建和注释项，在空业务库以应用角色恢复其余内容。恢复时使用 `--single-transaction --exit-on-error --no-owner --no-acl`。将核验过的 `application.tar` 解压到目标项目的空 `application_data` 卷，保留 UID 10001 的应用文件访问权。再按验收场景核对账号、会话、文献、知识库引用和计算记录。演练使用独立入口，并关闭原邮件发件和外部模型调用，直至完成数据核对。

回退时重新检出或构建已验证且与现有数据兼容的旧源码，沿用部署的 `.env` 与卷，并重新运行启动核对。存在不兼容迁移时，从升级前备份恢复到独立数据库核对后再切换。旧部署保持受控状态，避免误把空卷当作已有业务库。
