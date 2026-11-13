# V1.5 整体容器化：源码与操作稿

2026-11-09，基于 `62daa42` / V1.3，保留本轮此前的本地助手代码。对应[更新后的V1.5契约](../../PROJECT_PLAN_V1.5.md)和[容器方案](../../CONTAINER_DEPLOYMENT_V1.5.md)。

**以下为最初源码交付时的历史说明；随后已完成部分构建与验收，最新状态见[实际记录](../../test-records/v1.5.0/container-acceptance/20261109T020000Z/README.md)。** 没有拉取新镜像、安装虚拟机、导入容器模型、初始化/迁移个人数据库、停止原生服务或发布版本。OpenAPI/TypeScript生成、依赖版本清单生成、源码格式化不属于验收通过证据。下列操作是后续显式部署/验收的说明，本轮没有执行。

## 已写入的交付物

| 文件 | 实现范围 |
| --- | --- |
| `compose.yaml` | 前端、后端、独立PostgreSQL16+pgvector及Ollama；CPU为基础路径 |
| `compose.plotting.yaml` | 内部受信任执行器，仅该服务使用Docker Desktop Socket；不发布端口 |
| `compose.gpu.yaml` | 可选NVIDIA设备，仅交给Ollama，不授予Web或绘图任务 |
| `containers/application/Dockerfile` | 后端/执行器独立构建目标；后端目标没有Docker CLI或daemon证书 |
| `containers/frontend/Dockerfile` | Vue构建与Node静态代理；不接受含密钥的构建变量 |
| `.dockerignore` | 源码允许清单；排除.env、模型、备份、个人数据、产物和缓存 |
| `containers/application/requirements-runtime.lock` | 原生已准备依赖的精确版本清单，加Linux keyring依赖；不是Linux安装通过记录 |
| `scripts/lock_container_images.py` | 从本机已缓存的官方仓库镜像记录不可变摘要；拉取需额外显式参数 |
| `scripts/prepare_container_deployment.py` | 生成独立私有配置和凭据；已有目录拒绝覆盖，默认不读取原生密钥 |
| `scripts/containers.ps1` | Windows本机Docker入口，启动/停止/状态、准备模型卷、离线导入和读取身份 |
| `scripts/container_database.py` | 容器整库一致性备份与恢复到新数据库；不连接宿主PostgreSQL |
| `containers/model-source.json` | 已准备GGUF与原始模板/参数/许可证的固定哈希，供明确准备导入时核对 |

基础镜像必须由 `repository@sha256:...` 输入；未配置会拒绝启动构建。`containers/images.example.json`只是候选标签，**本轮没有解析其实际摘要，也未确认这些Linux镜像/轮子和硬件的兼容性**。Python3.12、Node24、PostgreSQL16及CPU PyTorch等精确依赖仍需在后续构建和验收中核实；不能凭Windows安装记录声明Linux已经可用。CPU轮子采用官方PyTorch CPU索引，不为RAG安装CUDA工具链。

## 网络与凭据

仅前端发布 `127.0.0.1:5173`。`web`、`database`、`models`及绘图的`execution`为分开的内部网络；后端保留科研服务出口，执行器只接入内部执行网络。没有发布8000、5432、11434、8090或Docker控制端口到宿主/局域网。网络划分不等于完整出站防火墙。

服务端显式 `ASTROAGENT_DEPLOYMENT_MODE=container` 才允许固定 `postgres:5432`、`ollama:11434`；原生模式仍仅接受既有回环地址。绘图仅允许 `plot-executor:8090`。前端固定代理 `backend:8000`，重设Host并去掉客户端伪造的代理头，再附加独立代理凭据。容器后端只接受该凭据和本机5173网页来源；`/health`为独立只读存活接口。接口文档改为同源 `/docs`，原生Vite和静态服务也代理这一路径。

密码、回答模型配置、代理凭据、执行器凭据通过Compose按服务挂载文件，在运行时读取；不进入镜像、前端或构建参数。后台应用使用独立非超级用户数据库角色。私有目录在Windows限制ACL，Linux父目录0700；单个只读秘密文件设0444以适配Compose文件挂载和非root UID，宿主访问仍受私有父目录限制。Compose secrets不是加密密码库，目录和备份仍应由用户保管。原生密钥保持原位，默认不会复制。

前后端/执行器采用非root、只读根、能力删除、禁止提权、独立tmpfs和资源/日志上限；Ollama模型卷可写，PostgreSQL保留其镜像初始化所需权限。后端健康只表示API进程存活；空库需要设置页明确初始化，Ollama或执行器缺失不阻止读取现有历史。数据库会话锁丢失时只重连并核对schema/扩展和单worker锁，不创建表、迁移或重放任务；另一进程已占锁则拒绝访问。

## 首次准备（后续操作，未执行）

Windows从 `D:\project\astroagent` 运行，Python入口沿用D盘专用环境；下例路径对应此前已准备的模型，实施时仍须核对实际文件。Docker Desktop镜像/卷的实际存储位置由其磁盘设置决定，本方案不自动移动Docker虚拟磁盘。

1. 先备份原生数据，核对Docker Desktop Linux容器和D盘剩余空间。新部署不连接原生5432、不搬迁数据；启动前处理前端5173端口冲突。本轮未代为停止现有服务。
2. 查看候选标签，按实际可用和审核版本调整自己的候选JSON。若镜像已缓存，记录摘要：

   ```powershell
   & 'D:\astroagent-runtime\venv\Scripts\python.exe' scripts/lock_container_images.py
   ```

   缺镜像时脚本报错；只有明确增加 `--confirm-download-images` 才执行拉取，不启动容器。锁文件含实际镜像ID/摘要及平台，标记构建未验证，拒绝覆盖旧锁。Linux可加 `--rootless` 使用当前用户本机socket；脚本不使用远程Docker上下文。
3. 生成新的私有配置。此操作不启动容器、不导入模型、不建业务表；以下SHA仅是此前嵌入目录的身份记录：

   ```powershell
   & 'D:\astroagent-runtime\venv\Scripts\python.exe' scripts/prepare_container_deployment.py --image-lock .astroagent/container-images.lock.json --embedding-model-dir 'D:\astroagent-models\minilm-v1' --embedding-sha256 1daaecb5ccf506a52cd67ffa88319d56efff7112b6f02b6f3d06a51e92f45d39 --prepared-qwen-dir data/v1.5-model-preparation
   ```

   输出 `.astroagent/container/deployment.env`、`secrets/`、`Modelfile` 和镜像锁副本。Qwen准备会读取并核对GGUF及元信息哈希，保留已下载官方模板、参数和许可证，不重新下载。准备失败会保留新建文件排查，已有目录不会被覆盖。
4. 如确需沿用原生远程服务配置，在首次生成命令同时明确增加 `--copy-native-provider-settings --confirm-include-credentials`；仅复制回答服务/ADS相关字段到后端秘密文件，不复制数据库密码、原生路径、会话或模型。否则新容器的远程密钥为空，需自行填写私有 `backend-settings.json`。修改只读文件时先临时赋予本人写权限，保存后恢复只读；不得打印或提交该文件。
5. 后续明确部署时运行：

   ```powershell
   powershell -File scripts/containers.ps1 -Action up
   ```

   该命令会执行构建和启动，可能需要下载Linux基础层及Python/Node依赖；本机Windows安装包/venv不能直接当作Linux镜像使用。构建步骤安装锁定版本并核对依赖，发生错误须保留记录，不声明部署成功。
6. 打开 `http://127.0.0.1:5173/settings`，页面应显示“独立容器部署”。新PostgreSQL卷首次启动仅准备独立角色、数据库和vector/pg_trgm扩展；**应用业务表、助手表和绘图表仍须分别在界面明确确认**。新卷不是旧数据迁移完成的证据。

停止用 `scripts/containers.ps1 -Action stop`，不删除任何卷。重新执行up沿用原卷。勿将 `down -v`、删除数据目录或覆盖原数据库当作排错步骤。

## Ollama离线导入与RAG

宿主Ollama缓存与容器`ollama_data`卷互相独立。先明确准备模型卷的非root写入权限，再显式导入：

```powershell
powershell -File scripts/containers.ps1 -Action prepare-model-storage
powershell -File scripts/containers.ps1 -Action import-model
powershell -File scripts/containers.ps1 -Action model-identity
```

第一步只调整此命名卷根目录归属；第二步将只读挂载的GGUF通过内部服务导入新卷，只有用户调用这个工具时执行；第三步只读注册身份，不推理。必须使用容器实际返回的完整摘要填写私有 `deployment.env` 中 `LOCAL_MODEL_DIGEST`，再明确设置 `LOCAL_MODEL_ENABLED=true`并重建/重启后端。不能直接沿用宿主注册摘要或仅根据模型名认定身份一致。之后还需设置页准备记录、开启助手/自动命名。缺少权重、配置或服务时不自动拉取或转远程。

嵌入模型只读挂载 `/models/embedding`。`RAG_SEMANTIC_ENABLED`初始false；核对目录身份与索引关系后再明确启用，后续在知识库中构建/重建索引。`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`禁止运行时下载。实际文件、依赖或索引不匹配时按既有规则显示降级，不因此宣称语义检索就绪。Linux需保证公开模型文件能被10001 UID只读访问。

GPU为可选：准备驱动、Docker GPU支持后才以 `-WithGpu`启动；CPU是默认部署，不承诺本机GPU可用或具体延迟。两种模式资源占用均待实测。

## Docker Desktop 内部绘图执行器

不使用 VMware 或额外 Ubuntu 虚拟机。`plot-executor` 是不发布宿主端口、仅接入 `execution` 内部网络的受信任服务；Web 后端和绘图任务不挂载 Docker Socket。执行器通过认证且字段严格受限的接口接收数据和脚本，复用 Docker Desktop 的固定协议2镜像；输入经独立卷传递，绘图容器无网络、非root、只读根、禁用全部能力、禁止提权，并限制 CPU、内存、进程数、文件、输出与时间。结束、异常和重启按自有标签清理。

**残余风险：** 执行器自身必须访问 Docker Desktop 守护进程，Docker Socket 即使以只读方式挂载也可以发送改变状态的 API 请求，实际具有控制同一守护进程内容器、卷和允许挂载的宿主文件的高权限。受限 HTTP 接口、网络隔离、非root 和认证只能减少攻击面，不会让 Socket 成为真正的只读或细粒度权限；执行器被攻破时风险高于独立 VM。不要将执行器端口、Socket 或凭据暴露给浏览器、Web 后端容器外的网络或绘图任务。此部署只面向受信任本机环境，不宣称可安全承载公网或恶意多租户。

准备时使用 `prepare_container_deployment.py` 的 `--plot-python-image`、`--plot-gnuplot-image` 填写现有协议2镜像的完整本机 sha256 ID，并通过 `--docker-socket-gid` 填入实际套接字所属组；本机检查值为0，实际运行前应重新核对。随后 `scripts/containers.ps1 -Action up -WithPlotting`；执行器不可用时禁止执行且不回退宿主。

执行器维护记录仅包含UUID、哈希和状态；清理失败保留标记并拒绝新任务。需要清除旧的去重记录时，先停止执行器，按原维护入口显式执行并确认。

## 备份、恢复和旧数据迁入

绘图的已保存PNG/PDF、脚本、数据与清单均在现有数据库事务中保存，因此一致性`pg_dump`包含这些字节以及会话、文档、向量；无需另存临时任务卷或模型。完整备份可能包含私人材料，操作必须明确确认：

```powershell
& 'D:\astroagent-runtime\venv\Scripts\python.exe' scripts/container_database.py backup --output 'D:\AstroAgentBackups\v15.dump' --confirm-include-originals
```

输出custom dump与SHA-256/字节数/公开模型及镜像身份清单，标记恢复未验证。不覆盖已有备份；失败的`.partial`保留，不能当成功备份。私有密码、代理/执行token、证书和模型权重不进入这份备份，凭据须另行安全保管；执行器owner/去重元数据需在停止执行器后另做受控运维备份，不混入公开源码。

恢复首先使用独立Compose项目/卷演练，仅启动其PostgreSQL，再指定全新数据库名和已核对备份SHA：

```powershell
& 'D:\astroagent-runtime\venv\Scripts\python.exe' scripts/container_database.py --project astroagent-v15-restore restore --backup 'D:\AstroAgentBackups\v15.dump' --expected-sha256 <完整SHA256> --new-database astroagent_restored --confirm-trusted-backup
```

维护工具固定访问本机Docker和指定Compose实例，不读取宿主数据库。原子创建新库，目标已存在即失败；预装受控扩展，过滤备份里的同名扩展定义/注释，再以普通应用角色在单事务恢复对象，不恢复原账户密码。失败保留新目标排查，不DROP、不覆盖日常库。成功只表示命令完成，仍须独立核对计数、原文、向量身份、图像字节、助手和科学功能。

原生数据迁入时，先用现有 `scripts/manage_postgres.py` 在原生环境显式备份，确认真实源库和原文范围；再使用上述容器恢复路径到独立新库。通过验收后才明确修改容器配置`CONTAINER_DATABASE`并重启后端；原生数据库始终保留。不能将新卷的首次初始化当作旧数据已迁入。回退则停止新容器、恢复原生启动方式；不要自动删除任何卷或旧库。

## 未完成的运行证据

以下为最初交付时的待验收清单，后续结果和未覆盖项以[实际记录](../../test-records/v1.5.0/container-acceptance/20261109T020000Z/README.md)为准。既有V1.3原生绘图验收不能转记为V1.5容器验收。M4源码和操作稿已提供，环境实施和M5验收仍待用户安排。

实现参考：[Compose启动依赖](https://docs.docker.com/compose/how-tos/startup-order/)、[Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)、[Docker daemon TLS保护](https://docs.docker.com/engine/security/protect-access/)、[固定tar输入传输](https://docs.docker.com/reference/cli/docker/container/cp/)、[pgvector镜像](https://github.com/pgvector/pgvector#docker)、[Ollama容器CPU/GPU入口](https://docs.ollama.com/docker)。这些文档说明接口与配置依据，不代替本项目运行证据。
