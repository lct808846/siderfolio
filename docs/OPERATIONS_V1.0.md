# V1.0 安装、配置、迁移与维护操作稿

**2026-11-01：以下命令本轮均未执行。源码已写入，平台安装、数据库/模型、迁移、构建及恢复均待验收。** 不据此宣称环境已安装或服务已启动。V0.9历史操作保留在 [旧操作稿](OPERATIONS_V0.9.md)。

后续用户已要求准备数据库并接入DataGrip；实际本机16.15/pgvector0.8.6、schema6初始化、凭据文件和启停方式见 [本机接入记录](development/v1.0.0/DATABASE_SETUP.md)。该记录补充真实部署时点，不把下面的全部操作稿命令或完整验收改记为已执行。

2026-11-02，用户另行要求语义检索达到可用状态，已准备 D 盘固定模型与 CPU 推理环境，完成隔离文档上传、索引和中英文语义预览核验，并启动本机前后端。实际路径、专用启动入口、耗时和核验边界见 [模型准备记录](development/v1.0.0/MODEL_SETUP.md)，不代表以下全部操作稿均已验证。

## 数据库准备

候选目标为本机PostgreSQL17.3+或18、pgvector0.8.7及pg_trgm，最终支持版本以当次Windows/Linux验收记录为准。数据库仅监听loopback，使用独立账号和数据库；后端仍单进程单worker。安装扩展到服务器与在数据库中启用扩展是两个步骤，安装Python驱动不等于安装数据库。

Windows原生安装PostgreSQL后，可按 [pgvector官方Windows说明](https://github.com/pgvector/pgvector#windows)在Visual Studio x64 Native Tools管理员终端编译。下面是CMD语法，路径必须改为真实安装位置，不能在PowerShell直接照搬set语法：

```bat
set "PGROOT=C:\Program Files\PostgreSQL\18"
git clone --branch v0.8.7 https://github.com/pgvector/pgvector.git pgvector-v1-build
cd pgvector-v1-build
nmake /F Makefile.win
nmake /F Makefile.win install
```

Linux可使用与服务器主版本一致的发行包；已配置PostgreSQL官方APT仓库的Debian/Ubuntu示例为 `sudo apt install postgresql-18-pgvector`。其他发行版及本机已有服务不能据此假定兼容，按 [官方安装选项](https://github.com/pgvector/pgvector#installation)选择。没有假定用户安装Docker，也未在本轮安装系统软件。

以数据库管理员通过本机 `psql` 准备独立账号，交互设置密码而不把真实密码写进命令历史：

```sql
CREATE ROLE astroagent LOGIN;
\password astroagent
CREATE DATABASE astroagent OWNER astroagent;
\connect astroagent
CREATE EXTENSION vector;
CREATE EXTENSION pg_trgm;
```

正常运行账号不需要超级用户；初始化需要建表/扩展能力，管理员可先启用扩展再交给库所有者。用于验收的账号/数据库必须另外创建，不能把日常astroagent库当测试目标。

## 前后端与首次配置

Windows在独立环境、源码根目录执行的示例：

```powershell
conda create -n astroagent-v1 python=3.12
conda activate astroagent-v1
python -m pip install -e ".[dev,rag]"
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
# 在服务端.env填写ASTROAGENT_DATABASE_URL，禁止VITE_前缀或提交真实密码。
python -m uvicorn astroagent.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Linux对应独立环境：

```bash
python3 -m venv .venv-v1
. .venv-v1/bin/activate
python -m pip install -e '.[dev,rag]'
test -e .env || cp .env.example .env
# 编辑服务端.env中的本机连接，真实凭据不写进版本仓库。
python -m uvicorn astroagent.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Sentence Transformers依赖PyTorch，CPU包的体积与平台适配需在实际安装前核对；本轮没有安装、下载或加载它们。Node目标为24.15+的24.x，第二个终端在 `frontend/` 执行：

```text
npm ci
npm run build
npm run serve
```

访问 [本机设置](http://127.0.0.1:5173/settings)。核对数据库状态后点击确认初始化空库，再进入项目。连接无效、权限不足、扩展缺失或schema不符时不能用SQLite冒充正常。配置通过服务端环境修改并重启生效；浏览器不保存数据库密码或模型密钥。无回答密钥仍可管理项目和检索原文。

## 固定本地模型

模型目录与向量另设预算，初值2 GiB/128 MiB；CPU子进程限120秒及3 GiB。候选模型尚未做本版效果或资源验收，不声明它已适合全部中英文天文问题。先按模型卡检查许可，并选定40位提交SHA；下面的尖括号内容需替换，不是可用版本号。

```powershell
python scripts/prepare_embedding_model.py describe --revision <固定40位提交SHA>
# 核对上一步来源、许可、下载字节与预算后，再显式下载到全新目录。
python scripts/prepare_embedding_model.py download --revision <同一SHA> --directory "D:\astroagent-models\minilm-v1" --maximum-bytes 2147483648 --confirm-download
```

工具只下载固定公开仓库允许的模型配置/安全权重文件，不调用回答模型，不传文献。按 [Hub固定版本下载接口](https://huggingface.co/docs/huggingface_hub/guides/download)编写，实际下载未执行。已有离线目录可使用：

```powershell
python scripts/prepare_embedding_model.py fingerprint --directory "D:\astroagent-models\minilm-v1"
```

将目录与打印的整目录SHA分别写入服务端 `ASTROAGENT_RAG_MODEL_PATH` / `ASTROAGENT_RAG_MODEL_SHA256`，维度默认384，重启后端。运行时 `local_files_only=True`、禁止远程模型代码，绝不自动下载或换模型。项目内显式构建索引，失败可继续词法检索；需重建时新代完成后才切换。历史版本若无向量覆盖会标记降级，不能宣称全部文档已语义索引。

## 从V0.9迁移

1. 停止V0.9服务，使用旧 `manage_data.py backup` 保存schema5一致性备份及SHA清单；保留旧源码与原备份，不直接复制正在写入的SQLite主文件。
2. 准备独立空PostgreSQL数据库，配置服务端连接并停止V1后端，避免单进程锁冲突。
3. 显式执行只读迁移。输入必须是停服后的完整备份，不能传日常活动库；脚本不升级低版本SQLite。

```powershell
python scripts/migrate_sqlite_to_postgres.py --source "D:\astroagent-backups\before-v1.sqlite3" --expected-sha256 <清单中的SHA256> --report "D:\astroagent-backups\migration-v1-report.json" --confirm
```

逐表比较原JSON、ID、关系、文件字节和计数的摘要；失败回滚目标导入事务，不删除源或已有目标。目标表结构可能已初始化为空，失败文件保留排查。没有自动迁移或运行这条命令。迁移报告不是词法质量、原文浏览器或故障恢复验收，仍需独立核对。

切换后新写入不会回流旧SQLite。回滚V0.9需停服并恢复迁移前备份；不能让旧程序写PostgreSQL或把V1新数据误当已经回写。向量是派生数据，迁移后在项目内明确构建。

## 备份与两种恢复

整库工具调用 [pg_dump一致性备份](https://www.postgresql.org/docs/current/app-pgdump.html)，包含业务原文、问答、向量及模型标识，不包含服务端环境密钥或模型文件；账号/服务器全局配置另管。客户端工具应与服务器版本匹配并在PATH中，凭据只经子进程环境传递，不放在命令参数或报告。

```powershell
python scripts/manage_postgres.py backup --output "D:\astroagent-backups\v1.dump" --confirm-include-originals
python scripts/manage_postgres.py restore --backup "D:\astroagent-backups\v1.dump" --expected-sha256 <备份清单SHA256> --new-database astroagent_restored_v1 --confirm-trusted-backup
```

恢复仅接受用户可信的自建备份，在从未存在的新库创建目标，`pg_restore --single-transaction --exit-on-error`，不覆盖已有库、不自动启动应用。恢复数据库备份会执行其中数据库定义，不能把任意外部下载的dump当作惰性项目JSON；该行为区别见 [pg_restore官方说明](https://www.postgresql.org/docs/current/app-pgrestore.html)。恢复失败保留新目标排查，不自动DROP数据库。用户账号须有创建新库权限，不能为便捷扩大日常服务权限；必要时使用独立维护环境账号。

生成备份/恢复退出成功仍需独立核对schema、pgvector、计数、文件哈希、固定引用、模型与向量维度；缺本地模型时显示需要准备，不自动下载。两平台完整演练尚未执行。

项目迁移则在页面使用格式5 ZIP：完整包须确认含原文，仅元数据缺原文不可用；导入为独立新项目并标记来源未认证，向量需重建。ZIP不是整库备份，问答文字与旧聊天即使在仅元数据包中也可能存在，不代表匿名化。

## 使用、故障与卸载

项目→上传文献→核对解析→知识问答→构建索引→输入问题/文档范围→查看全部发送片段/历史/模型服务→确认→逐项原文回查。无证据、无密钥、模型超时、索引未就绪、无效引用和文本变化均有独立状态；不根据模型记忆补充科研测量。

修改服务端连接或模型配置需重启。`/health`仅证明进程存活，设置页状态不证明Gaia、ADS或模型连通。Gaia的旧超时根因未确定；本轮仅新增显式诊断材料 `python scripts/diagnose_gaia.py --run`，没有运行或声称修复。

卸载时先停止本机前后端，按实际环境删除源码/虚拟环境；默认保留PostgreSQL服务及数据目录、本地模型、旧SQLite备份、dump、项目ZIP和下载文件。是否删除数据库/原文由用户另外明确决定；本工具不自动删除日常数据。物理数据库/WAL/备份还需额外空间，业务限额不承诺整个磁盘占用上限。
