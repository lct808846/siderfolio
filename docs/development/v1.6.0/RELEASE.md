# AstroAgent v1.6.0

V1.6.0 是 AstroAgent 的正式源码版本。Python 包、前端包和应用容器统一采用 `1.6.0`。

- 支持邮箱激活、登录、密码恢复、多因素认证、逐会话退出和按账号隔离科研数据。
- 提供个人资料、头像及账号统计，并完善侧栏、设置和窄屏布局。用量统计来自已保存的请求记录，服务商账单以服务商为准。
- 支持配置多个模型服务商及 OpenAI Chat、OpenAI Responses、Anthropic、Gemini 四种协议。密钥加密保存在服务端。
- Docker Desktop 和 WSL2 部署继续为 Python/Gnuplot 任务提供网络隔离、非 root、只读文件系统与资源上限。内部执行器对 Docker 守护进程仍有高权限，部署边界见[操作说明](OPERATIONS.md)。

本轮从 RC1 升级时，修复了科研流程测试连续运行会共用合成超时记录的问题，补充了 Gaia 归档和 ADS 证据表的 HTTP 与下载核验。身份、个人资料、模型服务商及布局的既有验收范围见[增量记录](../../test-records/v1.6.0/changed-parts/20261116T071217Z/README.md)和[验收清单](ACCEPTANCE.md)。

[操作说明](OPERATIONS.md)包含部署、认证密钥和数据卷说明。GitHub Release 提供源码包。本次未重复测试真实 SMTP、第三方模型额度、外部天文服务或公网多用户部署。
