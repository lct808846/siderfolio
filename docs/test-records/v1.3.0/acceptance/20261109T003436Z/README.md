# V1.3 改动范围验收

开始于 2026-11-09 00:34:36 UTC，基线 `cc00e3b`，在隔离数据库和合成数据上验证本次绘图及其直接影响。最终版本提交和远程检查以 GitHub 对应提交为准。

- 后端项目与归档回归 34 项、既有 Gaia 图和导出回归 187 项通过；绘图数据和沙箱针对性测试见 `plot-unit.xml`。前端类型、lint、33 项单元测试和生产构建通过，OpenAPI 类型一致。
- 最终容器镜像在 Windows Docker Desktop Linux 后端上，Python 与 Gnuplot 各执行散点、折线、直方图和误差棒，8 项均生成 PNG 和 PDF；实际图片及记录见 `sandbox-matrix.json`、`python-scatter.png`、`gnuplot-scatter.png`。
- 真实配置的 `deepseek-v4.1-flash` 接收四行合成数据，各生成一次 Python 和 Gnuplot 散点方案，均成功执行，调用分别使用 2279、2305 tokens；金额由服务商计费信息确定。脚本及 `live-model.json` 留存，未发送私人资料。
- 中文字体补充后，使用上述真实模型脚本重绘并检查 `python-chinese.png` 和 `gnuplot-chinese.png`。`python-chinese-first.png` 留存修复前的方框问题。
- 临时 PostgreSQL 测试库覆盖明确同意后生成、确认执行、重放、单文件与 ZIP 字节和哈希一致、格式6项目归档恢复以及导入脚本不得直接执行；测试结束后删除测试库。
- Chromium 与 Edge 的绘图确认流程和项目归档浏览器回归各通过；绘图页面请求由模拟服务提供，真实 PostgreSQL 和容器链路另有上项测试。
- 最终 Windows Docker Desktop Linux 镜像的网络隔离、根目录只读、敏感环境变量不传入、符号链接输出拒绝及超时后清理通过，见 `sandbox-security.json`。容器 CPU、内存、交换、进程数和非特权配置由执行前检查验证；没有穷举全部内核攻击或硬件平台。
- WSL Ubuntu 使用临时 Docker Desktop 共享套接字和路径映射适配器，Linux 侧沙箱代码的两个引擎通过；其错误类为测试替身，未修改 WSL 系统配置，不能等同于独立 Linux 主机完整集成验收。首轮路径映射失败及诊断保留。

首次 Ruff 和前端类型检查失败已修复并复测。原容器使用 tmpfs 输出，容器退出后无法取回产物；现已改为退出前传输并校验归档。首次中文字体配置仍产生方框，已补充 Matplotlib 实际识别的字体并复测。原始失败和重试记录保留。

本机模型结果与合成数据不能证明任意科研结论、所有模型和脚本的正确性。未使用个人业务数据库或个人文献；真实外部 Gaia 等旧版联网验收不在本轮改动范围。

同步为正式版本号 `1.3.0` 后，再次通过绘图数据、沙箱和既有导出共 64 项；真实 PostgreSQL 绘图与归档链路重新通过，前端 lint、类型和生产构建通过。最终版本的 CI 以远程实际运行结果为准。
