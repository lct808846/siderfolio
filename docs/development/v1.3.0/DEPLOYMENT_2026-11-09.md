# 本机容器部署记录

**后续验收更新：** 协议1镜像已被协议2替代，本机配置现固定验收通过的 Python 镜像 `sha256:fd4b97c08fc6c0bb530644720111b870fed2447fb86e05d894b9837827046cfa` 和 Gnuplot 镜像 `sha256:606fea82eef7cd702d88f894fb4b0f4efe028c7924c44801b31319221ebb1bbc`。已运行的后端进程需要重启后才会读取新配置；没有初始化个人绘图数据库。[验收记录](../../test-records/v1.3.0/acceptance/20261109T003436Z/README.md)保留失败和复测证据。下文是安装时的历史状态。

日期：2026-11-09（Asia/Shanghai）。用户明确要求开始部署容器环境。
本记录只证明软件安装、镜像构建、配置和本地服务启动，不作为 V1.3 绘图功能验收或发布证据。

## 已完成部署

| 项目 | 实际状态 |
| --- | --- |
| Docker Desktop | 4.98.0.245422，官方安装包，Docker Inc 数字签名 Valid，安装退出码0，无需重启 |
| 程序目录 | `D:\Program Files\Docker` |
| Docker Engine | 29.9.2，Linux，WSL 2 |
| 容器数据盘 | `D:\DockerData\disk\docker_data.vhdx` |
| Docker WSL 系统盘 | `D:\DockerData\main\ext4.vhdx` |
| 原 Ubuntu | `D:\WSL\Ubuntu`，仍为原 WSL 2 发行版，本轮未重装或启动 |
| Python 镜像 | `astroagent-plot-python:1.3`，numpy 2.2.6 / matplotlib 3.10.3，构建成功 |
| Gnuplot 镜像 | `astroagent-plot-gnuplot:1.3`，独立 gnuplot-nox 5.4.4，构建成功 |
| 后端 | `http://127.0.0.1:8000`，启动完成，配置接口返回200 |
| 前端 | `http://127.0.0.1:5173`，Vite 本地开发服务，入口 HEAD 返回200，未构建生产前端 |

Windows 内核/WSL：WSL 3.0.3.0，Linux 6.18.54.1-microsoft-standard-WSL2。
Docker 元数据表明 MemoryLimit、SwapLimit、PidsLimit、CpuCfsQuota 均可用，内建 seccomp 已启用，无引擎警告。

Docker 安装包保留于 `D:\astroagent-runtime\downloads\docker\Docker Desktop Installer.exe`，实测623748528字节（约594.8 MiB），SHA256：

```text
cd6273d9eaa4f07fa7593fc6813d37e1004381cebc3f26047a2554fa5db24388
```

这只是安装包实际大小，不是整个部署网络流量计量。镜像依赖另行下载，两个引擎复用了同一基础镜像。

## 固定镜像身份

Python：

```text
sha256:9de82a7057adb101426fd5bbab31424498dd22ef46ddc5ee2b94712b622beefd
```

Gnuplot：

```text
sha256:6f275fd724e749f121f31e9bf21b5a160c7dcf9b744d123ee0f64b179b6bbd3b
```

共同基础镜像解析为：

```text
python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
```

两份镜像均为 linux/amd64，配置用户65532:65532，绘图协议标签为1。
为核对 Docker 29 镜像 ID 表示方式，曾创建一个从未启动的元数据容器，确认镜像 ID 一致后立即删除；没有运行容器内命令或模型脚本。

项目忽略的 `.env` 已启用隔离绘图，并固定上述两份镜像 ID、30秒上限及本机 `npipe:////./pipe/docker_engine`。原模型和数据库配置保留，密钥未写入本文、构建上下文或日志。

## 存储与验收边界

部署后的只读配置接口返回：

```json
{
  "storage_ready": false,
  "execution_configured": true,
  "message": "执行配置已提供；每次执行前仍将核对Linux容器与资源限制。"
}
```

本轮没有初始化绘图扩展表。用户首次进入项目的「数据绘图」，点击「准备绘图数据库」并确认后才创建这些表。

本轮没有提交模型请求、调用真实科研服务、执行绘图、检查图像、运行项目测试/类型检查或构建生产前端；没有发布版本。绘图脚本、实际隔离执行、PNG/PDF与下载一致性、字体和项目归档兼容等仍按 [V1.3计划](../../PROJECT_PLAN_V1.3.md)安排验收。

## 启停与部署资料

使用前保持 Docker Desktop 运行。本地启动脚本：

```powershell
Set-Location D:\project\astroagent
.\scripts\start_backend.ps1
```

另一个终端启动前端：

```powershell
.\scripts\start_frontend.ps1
```

后端脚本已将 D 盘 Docker CLI 目录加入自身 PATH，使安装之前打开的终端也能发现 Docker。
前端脚本在自身进程设置 `CI=true`，避免 Vite 因后台标准输入关闭而退出；此设置不启动任何测试。

部署日志与非秘密配置摘要保存在本机忽略目录 `.astroagent/deployment/docker/`；本次服务日志为 `.astroagent/runs/20261109-082257-containers/`。
前端曾有一次重复启动因原服务已占用5173被拒绝，原 Node 进程保留并已确认入口响应；对应错误日志保留，不代表最终部署失败。

安装方式依据 [Docker Windows安装文档](https://docs.docker.com/desktop/setup/install/windows-install/)，后台启动依据 [Docker Desktop CLI](https://docs.docker.com/reference/cli/docker/desktop/start/)。
