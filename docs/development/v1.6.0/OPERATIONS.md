# V1.6 配置、部署与旧数据归属

2026-11-14执行补充：本机已按用户授权构建、测试并部署V1.6。用户随后明确选择清空旧业务数据，因此本次没有执行第4节的旧数据认领；先将V1.5备份恢复到独立验证库，逐表比较33张表的完整行及BLOB/向量SHA-256，一致后清空原容器业务库。原备份私密保留，Windows其他数据库未操作。完整证据见[本轮记录](../../test-records/v1.6.0/acceptance/20261114T081737Z/README.md)。以下仍保留未来安装、认领和恢复的操作说明。

当前私有环境为 `.astroagent/container/deployment-v16.env`，认证设置为 `.astroagent/container/secrets/auth-settings-v16.json`；密钥只首次生成，重建不会轮换。QQ SMTP已通过加密认证、提交及邮箱页面送达核对；个人账号和首次管理员没有默认创建。访问 `http://127.0.0.1:5173/register` 自行完成邮箱验证和设密。

`scripts/containers.ps1` 检测到独立V1.6环境后自动组合身份/绘图覆盖文件；可显式传 `-WithIdentity`。私有的 `compose-v16-shared-model.yaml` 将模型卷指向已有V1.5模型卷，启动不再次导入或更改共享模型目录权限。新增 `V16_BACKEND_SETTINGS_FILE` 可指定独立的V1.6私密科研服务设置，保留旧版本设置。新的个人数据库与模型卷是不同资源；复用模型不会复用旧业务库。

## 1. 准备配置

沿用V1.5固定摘要基础镜像、数据库密码、模型与执行器配置。复制到一个单独的V1.6部署环境文件，保留V1.5原件。不要把私有JSON、口令、邮箱令牌或备份提交Git。

V1.6需要额外的 `AUTH_SETTINGS_FILE`（私有文件绝对路径）与 `AUTH_SITE_ORIGIN`（公开固定站点origin）。认证配置格式见 `containers/auth-settings.example.json`，其内容全部为字符串。

- `ASTROAGENT_AUTH_SECRET`：Fernet格式32字节随机密钥，首次生成后须持久保管；重建镜像不能重新生成。失去它会使加密TOTP和待发邮件不可读。
- `ASTROAGENT_AUTH_ORIGIN`：实际浏览器访问地址，必须与 `AUTH_SITE_ORIGIN`、页面代理和邮件链接一致。回环HTTP测试可用 `http://127.0.0.1:5173` 并明确 `ASTROAGENT_AUTH_LOCAL_HTTP=true`；localhost是另一个origin，不能混用Cookie/CSRF。
- 远程必须HTTPS、local_http=false，且需要受控TLS反代和Host配置。Compose仍只发布127.0.0.1，不会自动开放公网端口。
- 提供SMTP主机、端口、TLS或STARTTLS、认证用户名、密码和发件地址；不支持明文SMTP。缺失时新注册和找回暂不可用。
- 默认随包提供固定哈希的离线常见密码词表；可覆盖词表路径与SHA-256，必须只读挂载到后端且不少于9000个不同条目。
- 默认1000个账号、每小时100封邮件、32个活动用户服务图。按实际资源和验收调整服务端上限；本版不宣称大规模生产承载。

密钥生成命令（在已准备身份依赖的隔离运行时本机执行，输出只保存到私有配置）：

```text
python -m astroagent.identity_cli generate-key
```

没有默认账号、默认密码、自动首用户管理员或公开初始化接口。

## 2. 容器顺序

所有V1.6命令组合下面三个文件，且使用新的私有环境文件：

```text
docker compose --env-file <V1.6私有env> -f compose.yaml -f compose.plotting.yaml -f compose.identity.yaml <操作>
```

在 Windows 使用已安装在 D 盘的 Docker CLI，并显式选择本机 Docker 引擎。此组合项目名为 `astroagent-v16`，应用镜像标签为 `1.6.0`。**新项目的默认卷为空，不会自动复用或迁移 V1.5 卷**。已有 V1.6 部署升级时沿用同名卷与私有配置。5173 端口与旧实例冲突，隔离环境须另配端口与完全匹配的 origin，或在安排部署时先停旧入口。

1. 用户安排后构建 backend/frontend/ingress/plot-executor；不在镜像中生成秘密或创建数据库。
2. 先启动PostgreSQL及必要内部依赖；新空数据库按既有容器入口安装public中的vector/pg_trgm扩展。
3. 后端保持停止，执行一次身份表初始化：

   ```text
   docker compose <上述配置参数> run --rm backend identity initialize
   ```

4. 初始化只创建auth表，不移动旧业务表，不提升任何用户。检查配置后，再由用户安排启动完整服务。
5. 用真实邮箱注册、收到邮件、主动确认、设密码并登录。用户首次访问业务时创建的是他自己的空schema。
6. 内部健康检查只验证进程，不能当作邮件、登录、模型、隔离或绘图通过证据。身份服务未初始化、密钥不符或数据库故障时，业务始终关闭。

本机CLI也通过容器入口加载挂载秘密；不要直接用 `--entrypoint python` 绕开秘密加载。生产构建前须确认Linux依赖锁及身份新增依赖可干净安装。

## 3. 初始化首位管理员

先用普通流程验证并激活目标邮箱。停止全部后端；该命令在已有任意管理员时拒绝首次初始化。

```text
docker compose <上述配置参数> run --rm backend identity bootstrap-admin --email <已激活邮箱>
docker compose <上述配置参数> run --rm backend identity bootstrap-admin --email <已激活邮箱> --apply
```

第一条仅预览，第二条显示目标身份并要求键入完整账号ID确认。该终端会显示所选邮箱，属于服务器本机受控操作，不应录入公开日志。启动后，管理员重新登录并在账号安全页绑定验证器、保存仅显示一次的恢复码，才可进入管理功能。

管理页通过手动输入 `/admin` 访问，网站不显示后台链接。角色授予/撤销、启禁用和邮件重试需要5分钟内的密码+验证码重新认证。管理端不提供科研内容阅读、SQL或命令执行。

验证器与恢复码丢失时，停止后端，由受OS权限保护的本机操作员预览并明确确认：

```text
python -m astroagent.identity_cli recover-admin-totp --email <既有管理员邮箱> --reason lost_authenticator
python -m astroagent.identity_cli recover-admin-totp --email <既有管理员邮箱> --reason lost_authenticator --apply
```

容器运行时改用 `backend identity ...`。此流程不重置密码、不提升普通邮箱，撤销旧会话并审计；恢复后仍须登录和重新绑定验证器。

## 4. 旧数据认领

V1.5数据不能默认归属首个注册账号。先用既有备份/恢复流程把可信V1.5副本恢复到隔离的V1.6数据库；不要把新项目空卷误认为旧数据已经迁入。

认领目标必须是已激活且未禁用的账号，并且其现有业务空间中没有业务记录。若账号已产生科研数据，命令拒绝合并，需另选一个已激活空账号，或另立迁移方案。只移动服务器白名单中的旧public表，发现未知表会停止。

1. 停止V1.5与V1.6全部后端，保留PostgreSQL。CLI同时核对旧仓储锁与新身份锁，服务运行时拒绝操作。
2. 身份表和目标账号准备好后，为这个确切的V1.6数据库生成新的全库备份：

   ```text
   python scripts/identity_backup.py --env-file <V1.6私有env> --output D:\AstroAgentBackups\v16-before-claim.dump --confirm-backend-stopped
   ```

   脚本通过目标Compose的postgres容器内pg_dump输出二进制，不把数据库密码放到命令行，不覆盖已有文件；保存SHA-256和清单。失败的部分文件会保留，不能当作有效备份。**哈希与PGDMP头只说明文件身份，不证明恢复可用或与待认领数据库对应；须由操作员先在隔离库恢复核对。**
3. 将已核对的备份只读挂入一次性维护容器 `/backups`，预览目标身份及表计数：

   ```text
   docker compose <上述配置参数> run --rm --volume D:/AstroAgentBackups:/backups:ro backend identity claim-legacy --email <已激活目标邮箱>
   ```

4. 明确确认后才执行：

   ```text
   docker compose <上述配置参数> run --rm --volume D:/AstroAgentBackups:/backups:ro backend identity claim-legacy --email <已激活目标邮箱> --backup-file /backups/v16-before-claim.dump --backup-sha256 <核对过的SHA256> --apply
   ```

   命令再次显示身份和表计数，要求输入目标账号ID。事务内创建新的私有schema、移动全部白名单业务表与关联对象、核对逐表计数、更新目标映射和审计；原目标空schema保留，不删除。记录/向量/文件BLOB原样移动，不重新编码科研结果。失败时事务回滚，备份始终保留。
5. 重启V1.6，使用两个独立账号验收旧记录、关联引用、RAG索引、绘图产物与导入导出；目标账号可读，其他账号不可读。单纯计数相同不能替代科学内容和完整性验证。

业务文件主要在数据库BLOB；临时科学ZIP/预览缓存可重新生成。既有独立绘图执行器账本/卷另行保留备份，未被本机认领命令删除或自动复制。

## 5. 恢复与降级

- 任何认领失败先保持后端关闭，检查事务是否回滚；不要自动猜测归属或删除旧备份。
- 使用已演练的备份恢复到新的隔离数据库，核对身份、表计数、向量及产物后再决定切换。不得直接覆盖唯一副本。
- 不能将V1.6带账号和新schema的数据直接交给V1.5，或重新开放匿名旧入口。若恢复V1.5历史副本，应保留V1.6账号/新增数据的独立备份，并明确它不包含后续写入。
- 数据库重启导致身份进程锁丢失时，业务和邮件工作器拒绝继续工作，须重启后端；不会一边失去维护锁一边执行认领。
- 浏览器已下载到磁盘的文件不受网站退出控制；网站退出清理应用缓存，但不能从用户磁盘撤回已下载文件。
