# V0.9 安装、升级、备份恢复与卸载操作稿

命令使用独立环境/数据目录示例；不要把新目录写成已有日常库。本版已在 Windows 与 Ubuntu 的独立环境作安装、构建和恢复检查，覆盖范围与 Gaia 超时限制见 [测试记录](test-records/v0.9.0/README.md)。具体支持范围见 [候选兼容契约](V1_CANDIDATE_CONTRACT.md)。

## Windows / PowerShell

源码目录示例为 `D:\project\astroagent`，需要Python3.12+与Node24.15+（24.x）。首次安装可使用独立conda环境；已有环境按实际选择，不能据此假定本机已有这些版本。

```powershell
Set-Location D:\project\astroagent
conda create -n astroagent-v09 python=3.12
conda activate astroagent-v09
python -m pip install -e ".[dev]"
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
$env:ASTROAGENT_DATA_DIR = "D:\astroagent-data-v09"
python -m uvicorn astroagent.main:app --host 127.0.0.1 --port 8000 --workers 1
```

第二个终端从源码根目录运行，安装与构建是发布前操作，本轮没有执行：

```powershell
Set-Location D:\project\astroagent
Push-Location frontend
npm ci
Pop-Location
powershell -File scripts/frontend.ps1 -Mode build
powershell -File scripts/frontend.ps1 -Mode serve
```

`frontend.ps1`可指定已安装受支持Node的 `-NodePath`；不要依赖别的机器上的Codex缓存路径。也可在 `frontend/` 中按 `npm ci`、`npm run build`、`npm run serve` 执行。前端只监听127.0.0.1:5173，通过固定代理访问127.0.0.1:8000。

## Linux

在已下载源码根目录使用独立虚拟环境；下面示例不安装系统包，不假定发行版和Node已准备好。

```bash
python3 -m venv .venv-v09
. .venv-v09/bin/activate
python -m pip install -e '.[dev]'
test -e .env || cp .env.example .env
export ASTROAGENT_DATA_DIR="$HOME/astroagent-data-v09"
python -m uvicorn astroagent.main:app --host 127.0.0.1 --port 8000 --workers 1
```

第二个终端在源码 `frontend/` 目录执行：

```bash
npm ci
npm run build
npm run serve
```

应用仅支持本机可信单用户、单worker；不使用多进程共享业务库。浏览器访问 [本机工作台](http://127.0.0.1:5173)、[项目入口](http://127.0.0.1:5173/projects)；项目内点击“项目总览与关联”。健康及API文档为 [health](http://127.0.0.1:8000/health) / [docs](http://127.0.0.1:8000/docs)，这些地址不是已启动状态的证据。

模型密钥与ADS token在服务端 `.env` 或环境变量配置，不能放前端 `VITE_` 中。没有密钥仍可读取本机历史、文档和关联；聊天需要模型密钥，ADS需要token，外部服务不可用时保留逐工具错误。创建关联不调用模型、不把文献发给供应商。

## SQLite / FTS能力与故障

发布前按真实环境核对Python、Node、SQLite及依赖版本，显式检查FTS5 unicode61、trigram和JSON函数。以下PowerShell片段仅检查内存库，尚未执行：

```powershell
@'
import sqlite3
with sqlite3.connect(":memory:") as db:
    db.execute("CREATE VIRTUAL TABLE words USING fts5(text, tokenize='unicode61')")
    db.execute("CREATE VIRTUAL TABLE grams USING fts5(text, tokenize='trigram')")
    print(sqlite3.sqlite_version, db.execute("SELECT json_extract('{\"v\":1}', '$.v')").fetchone())
'@ | python -
```

Linux可将同一Python内容保存为临时脚本执行；不要在个人库中建试验表。FTS/JSON能力缺失时知识库索引功能不可用；旧聊天/项目不因解析保护失败而退回无限制解析。Windows Job Object及Linux资源限制、30秒解析超时仍需本版环境实测。

## 升级与整库备份

升级前确认旧进程与目录，先保留一致性备份。默认业务库为源码目录下 `.astroagent/astroagent.sqlite3`，也可能由 `ASTROAGENT_DATA_DIR` 指向别处；不能只凭示例路径判断自己的库。

新增工具使用SQLite备份API，不直接复制正在使用的主文件：

```powershell
python scripts/manage_data.py backup --database "D:\astroagent-data\astroagent.sqlite3" --output "D:\astroagent-backups\before-v09.sqlite3"
```

输出必须是新文件，并生成 `.manifest.json`，记录schema、字节数、SHA-256和创建时间。它不包含 `.env`、Python/Node环境或前端构建。可对运行中的SQLite取一致性快照，但最容易核对的升级过程是先停服再备份；备份中的运行中任务在恢复启动后会中断标记，不自动重放远端操作。

V0.9首次启动将schema4升级到5，升级前另保存 `migration-v5-<UTC时间>.sqlite3`。失败回滚，未知更高schema拒绝写入；若存储不可用，健康/旧无状态接口与本机历史功能的可用性需分别核对。迁移备份不可等同已经演练成功的恢复。

## 两类恢复

**整库恢复：** 先核对备份清单哈希，只能恢复到从未存在的新目录；工具不覆盖现有日常库，不启动或自动升级应用。

```powershell
python scripts/manage_data.py restore --backup "D:\astroagent-backups\before-v09.sqlite3" --new-data-dir "D:\astroagent-restore-v09" --expected-sha256 "替换为清单中的64位SHA256" --confirm
```

确认命令完成后，手动将 `ASTROAGENT_DATA_DIR` 改为该独立目录，启动对应版本，再核对项目、文档字节、快照、流程与关联。恢复旧版本时使用其支持的schema备份：V0.8不能写schema5；不能把新版主库直接交给旧程序。失败的新目标可能保留以供排查，工具不会自动删除；没有完整清单/成功结果的文件不能当作已确认备份。

**单项目恢复：** 网页显式导出格式4完整包，显示文档/版本数量及字节并确认；导入为全新ID项目，来源标为未认证。仅元数据包不含知识库原文件或提取原文，导入后相关证据/关联不可用，同哈希恢复且位置一致后才可重新核对。原项目和新项目不自动合并。

整库恢复保留原ID，项目包导入重映射ID；它们不是同一种操作。两种恢复均需在发布前独立目录演练，本轮未执行。

## 卸载与数据保留

先停止前后端进程。卸载Python包或移除专用环境前核对环境名称，例如 `python -m pip uninstall astroagent`；如果确实使用独立 `astroagent-v09` 环境，可退出后由用户删除该环境。Linux的专用虚拟环境也应先核对绝对路径再自行移除。

默认保留数据目录、`.env`、迁移/手工备份、下载的ZIP和原始文献。删除项目/文档只作用于业务记录，不表示安全擦除SQLite空闲页、旧备份或外部副本。程序不提供一键清空个人数据的卸载脚本；需要清理时由用户明确确认实际路径和保留范围。
