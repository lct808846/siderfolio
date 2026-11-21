# AstroAgent V1.7 PeTar 与计算页面增量验收

本轮覆盖 PeTar、程序选择、计算页面新增预设与导入，以及直接相关的 REBOUND 兼容性。功能验收在独立 Compose 项目 `astroagent-petar-qa-20261121t092707z` 中完成，使用本机 5287 端口、合成账号和独立 PostgreSQL 数据库。验收镜像对应工作区 `1.7.0-dev.0`。 [源码与镜像指纹](tested-images-and-source-verified.json)

| 验收项 | 结果 |
| --- | --- |
| 计算接口与旧数据 | API 可识别两种程序，拒绝未登记的程序。旧 REBOUND 草稿哈希、已有结果与 ZIP 通过兼容性检查。复制保留程序，切换程序后旧确认失效。第二个合成账号无法读取对方的任务或产物。 [API 核验](api-core-refined.json) |
| 双体数值 | 两组 PeTar 圆轨道样例均达到预设 `10⁻⁶` 阈值。最大相对周期偏差为 `1.96×10⁻⁷`，最大间距偏差为 `2.94×10⁻⁷ AU`。100 点非二进制采样同时核对了平动质心、不等质量、粒子顺序和单位换算。 [数值结果](api-core-refined.json) |
| 预设计算 | PeTar 的 3 体预设完成 12 yr，最大相对能量偏差 `2.27×10⁻⁸`。两种程序均完成 12 体 Plummer 预设的 204.1 yr。该样例的 PeTar 相对能量偏差为 `1.50×10⁻⁵`，超过告警阈值，界面正确提示。 [预设实测](api-presets-final.json) · [告警截图](petar-plummer-warning.png) |
| 最大网格与导出 | PeTar 的 128 粒子 × 512 时刻短程样例成功，导出 65,536 行。实验 ZIP 的六个清单成员通过 SHA-256 核对，指定时刻 SVG 与同一时刻预览一致。 |
| 取消、超时与恢复 | 实测终止 PeTar 本体进程，并在取消或超时后恢复下一项计算。真实 120 秒墙钟上限从排队到观察到终态用时 122.70 秒，运行临时目录已清理。停止 Worker 后草稿可保存，恢复后可运行。无网络、非 root、只读根目录、1 vCPU、512 MiB、24 进程及专用挂载均核对。 [边界实测](api-limits-final.json) |
| 页面 | Chromium 和 Edge 共 4 项通过。覆盖查询工作台进入计算、程序切换、模板保留所选程序、键盘操作、保存确认、刷新恢复、实验对比、切换空间、导入和质心归零。核对桌面 1440 px 与窄屏 390 px。 [浏览器结果](browser-accepted/run.txt) · [桌面](browser-accepted/chromium-petar-desktop.png) · [窄屏](browser-accepted/edge-picker-mobile.png) |
| 自动检查 | Python 和专用 PostgreSQL 共 14 项通过，前端预设单元测试 7 项通过。相关 Ruff、ESLint、计算 OpenAPI 核对和生产构建通过。 [Python](pytest-compute-refined.txt) · [前端](vitest-presets-refined.txt) · [Ruff](ruff-compute.txt) · [ESLint](eslint-compute-final.txt) |

第一轮双体的周期和间距偏差超限，收紧 PeTar 树步长后用原样例复验。修复了 CSV 导入静默跳过首条异常数据及改写非法粒子 ID 的行为，修复了开普勒生成器默认的 2 圈阻止保存草稿的问题，并保证长项目名称下侧栏标题完整。初次超时查询遇到测试前端重启返回 502。浏览器前几次复验遇到页面跳转尚未完成及合成账号正常触发的登录限流。原始失败记录保留，最终结果来自独立、稳定的复验。

数值验收结论适用于上述固定样例。12 体 PeTar 样例完成计算，精度以实测能量偏差为准。

本机前端和计算 Worker 已更新为通过验收的镜像，继续使用现有数据库和交接卷。两个程序就绪，入口健康检查通过。5 个验收容器、独立数据库卷和交接卷已清理。 [本机部署核验](local-deployment.json) · [验收资源清理](qa-cleanup.json)
