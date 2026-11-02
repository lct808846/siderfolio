# 本机 PostgreSQL 与 DataGrip 接入记录

2026-11-01，用户要求使用具有独立安装包、图形管理工具和 Windows 卸载入口的标准安装版，并进一步要求将程序与数据目录迁到 D 盘。已完成标准安装版迁移，服务、安装登记和卸载程序均指向 D 盘，C 盘原程序与数据目录已清理。本文是实际数据库安装与 DataGrip 接入记录，**不是 V1.0 发布前完整验收**。

## 当前配置：标准 Windows 安装版

| 项目 | 本机实际配置 |
| --- | --- |
| 安装包 | PostgreSQL 16.15-5，Windows x64，EnterpriseDB 签名有效，SHA-256 与 winget 清单一致 |
| 程序目录 | `D:\Program Files\PostgreSQL\16` |
| 数据目录 | `D:\PostgreSQLData\16` |
| Windows 服务 | `postgresql-x64-16`，Running，Automatic，随 Windows 自动启动 |
| 打开图形界面 | 开始菜单 → PostgreSQL 16 → pgAdmin 4；也可继续用 DataGrip |
| 独立卸载 | 设置 → 应用 → 已安装的应用 → PostgreSQL 16；卸载项与程序均指向 D 盘 |
| 数据库连接 | `127.0.0.1:5432/astroagent`，账号 `astroagent`，非超级用户 |
| 结构与扩展 | schema6、27 张 public 表；pgvector 0.8.6、pg_trgm 1.6 |
| DataGrip | `AstroAgent V1.0 (local)`，迁移后已重新打开并确认“测试连接”成功，原连接配置保留 |

安装包来源是 [PostgreSQL 官方 Windows 页面提供的 EDB 安装器](https://www.postgresql.org/download/windows/)，包含服务端、pgAdmin 和命令行工具；本机未安装可选 StackBuilder。pgvector DLL 和扩展 SQL 沿用原 conda-forge 0.8.6 包，已在标准版 16.15 上确认向量类型与距离运算可加载。这是本机安装结果，不代表全部平台组合已通过项目验收。

首次切换标准安装版时，先在 5433 安装服务、恢复备份并确认逐表行数与内容摘要一致，再停止旧实例并切换至 5432。之后按用户明确授权完成 D 盘迁移：刷新角色与逐库逻辑备份，停库制作完整冷备份并逐文件核验 SHA-256，使用官方卸载器移除 C 盘程序，再在 D 盘重新安装并复用完整数据目录。核对服务路径、实际 data_directory、27 张表的行数与内容摘要、pgvector/pg_trgm 和应用账号连接成功后，清理 C 盘原目录。仅监听 IPv4 loopback，项目 `.env` 的账号、密码和连接地址保持有效；原 MySQL 数据源保留。

本次完整备份保存在 `D:\PostgreSQLBackups\move-to-D-20261101T180537`，包含 `globals.sql`、`astroagent.dump`、`postgres.dump`、完整冷备份 `cluster`、逐文件 SHA-256 清单和逐表数据摘要。准备阶段曾遇到 pgAdmin 已关闭和副本文件 ACL 问题，均在卸载前停止并恢复原服务；修正后重新制作并核验备份，最终迁移完成。失败副本也保留在该备份目录中，未作为当前服务数据使用。

更早的项目内 `.astroagent/postgres-runtime` 与 `.astroagent/postgres/data` 仍保留，旧实例已停止；它们不是当前标准版的运行目录。

标准版管理员账号为 `postgres`。管理员与应用凭据另存于私有目录 `C:\Users\lct\AppData\Local\AstroAgent\PostgreSQL16`，本文不复制密码。DataGrip 直接读取 AppData 副本时曾报路径不存在；改用独立私有目录后连接成功，未确认前一种路径失败的根因。DataGrip 当前高级页环境变量为：

```text
PGPASSFILE=D:\PostgreSQL16-client\datagrip.pgpass
```

这个文件的 ACL 限当前用户及 SYSTEM。程序、数据库和 DataGrip 凭据均不依赖项目目录。认证设置参考 [DataGrip 官方说明](https://www.jetbrains.com/help/datagrip/postgresql.html)。

关闭 pgAdmin 或 DataGrip 不会停止数据库。可在 Windows“服务”中管理 `postgresql-x64-16`；`scripts/postgres.ps1` 已改为优先管理标准版服务，防止误启旧实例。`-Action status` 查看状态，`-Action start` / `stop` 需管理员 PowerShell。

切换备份位于 `.astroagent/postgres/backups/before-standard-install-20261101T092411Z.dump` 和 `.astroagent/postgres/backups/cutover-20261101T174101.dump`；安装清单位于被忽略的 `.astroagent/postgres-standard/installation.json`。卸载前应按 [维护操作稿](../../OPERATIONS_V1.0.md) 备份需要保留的数据。本次未迁移旧 SQLite、未写入合成业务样本、未启动 AstroAgent 或模型、未执行项目测试/构建/CI/发布。数据库安装与连接核验不替代完整项目验收。

---

以下为首次 conda 部署的历史记录。其运行路径、凭据路径和普通进程启停说明已被上面的标准安装配置替代。

## 已完成

| 项目 | 本机实际配置 |
| --- | --- |
| PostgreSQL | 16.15，Windows原生、独立conda-forge环境 |
| pgvector / pg_trgm | 0.8.6 / 1.6，已在专用库启用 |
| 连接 | `127.0.0.1:5432`，仅监听IPv4 loopback |
| 数据库 / 应用账号 | `astroagent` / `astroagent`，应用账号非超级用户 |
| 业务结构 | schema6，27张public表，未迁移旧SQLite或写入合成业务样本 |
| DataGrip | `AstroAgent V1.0 (local)`，JDBC 42.7.13，连接核验成功并已保存，表结构已展开 |
| 认证 | SCRAM密码认证，DataGrip使用pgpass；未在JDBC URL或聊天中填写密码 |

选择16.15是因为当次conda-forge Windows pgvector0.8.6包的libpq依赖限定16.15，避免混装不同主版本的扩展。来源是[pgvector官方列出的conda-forge安装渠道](https://github.com/pgvector/pgvector#conda-forge)。这项本机接入结果不等于新增整个PostgreSQL16系列或全部Windows/Linux组合的稳定支持声明。

运行环境位于 `.astroagent/postgres-runtime`，数据目录位于 `.astroagent/postgres/data`，服务日志为 `.astroagent/postgres/server.log`。全部位于既有Git忽略的本地数据目录；没有替换系统数据库或现有MySQL。

首次空库初始化遇到驱动对DDL无结果描述的行转换问题，已在 `postgres.py` 修正为允许空description；再次初始化成功。未因此运行项目回归测试、RAG评估、构建或发布。

## 凭据与应用连接

服务端 `.env` 已新建并填写 `ASTROAGENT_DATABASE_URL`。管理员、应用账号和DataGrip凭据文件只保存在本机被忽略的位置，ACL限当前Windows用户及SYSTEM；本文不复制密码。

DataGrip数据源常规页：PostgreSQL、127.0.0.1、5432、astroagent账号与同名库，认证方式pgpass。高级页驱动环境变量为：

```text
PGPASSFILE=D:\project\astroagent\.astroagent\postgres\datagrip.pgpass
```

这是本机文件路径，不是密码。认证与测试连接流程依据 [DataGrip官方说明](https://www.jetbrains.com/help/datagrip/postgresql.html)。原MySQL数据源保留，未修改其密码或数据。

## 启停

数据库当前以后台进程运行，**没有注册开机自动启动的Windows系统服务**。电脑重启后，在项目根目录执行：

```powershell
powershell -File scripts/postgres.ps1 -Action start
```

查看当前进程状态或明确停止：

```powershell
powershell -File scripts/postgres.ps1 -Action status
powershell -File scripts/postgres.ps1 -Action stop
```

停止会断开此实例的客户端连接，但不删除数据。脚本只使用本项目固定的数据目录，不创建/重置数据库，不读取或显示密码。备份与恢复仍按 [维护操作稿](../../OPERATIONS_V1.0.md)；旧SQLite保留，未自动迁移。

本次未启动AstroAgent前后端、未下载/加载嵌入模型、未调用外部科研或回答服务，未执行完整API/并发/迁移/恢复/资源/科学验收。DataGrip连接成功与可见表结构不能替代这些项目验收。
