# Siderfolio v2.0.0

V2.0.0 将项目正式更名为 **Siderfolio**（原 AstroAgent），交付面向个人和小课题组的服务器部署配置、多人使用配额与后台管理、开发与发布体系，并完成 V1.9.0 与 V2.0.0 的联合测试验收。

- **服务器部署与反向代理**：提供针对 Ubuntu 24.04 x86_64（如 GCP `n2-standard-2`）的生产 Docker Compose 编排、Caddy HTTPS 入口（支持域名或公网 IPv4 证书）、PostgreSQL + pgvector 初始化镜像及一键准备、部署、验证与备份脚本。 [GCP 部署说明](../../../containers/gcp/README.md) · [V2.0 开发文档](../../PROJECT_PLAN_V2.0.md)
- **多人配额、容量与后台审计**：在既有邮箱激活、管理员 TOTP MFA 和单账号 PostgreSQL schema（`aa_<32hex>`）隔离基础上，支持按账号配置每小时模型请求、天文查询、存储空间（MiB）和排队计算任务上限；达到限额时明确提示类别、已用量与恢复时间，不影响其他账号；后台提供计算队列容量与配额变更审计记录。
- **V1.9 + V2.0 联合验收与备份恢复演练**：完成个人天文文献库（手动入库与受服务端 `SavePermit` 授权的对话内直接入库、幂等回执、重入库保留标签与私人备注）、脱敏运行追踪与费用估算、REBOUND / PeTar 双体基准、真实隔离绘图、多账号隔离及 `pg_dump` / `pg_restore` 独立库恢复演练。 [V2.0 联合验收记录](../../test-records/v2.0.0/joint-acceptance/20261123T091033Z/README.md) · [V1.9 联合验收记录](../../test-records/v1.9.0/joint-acceptance/20261123T091033Z/README.md)
- **更名与向后兼容**：公开界面、标题、邮件、TOTP 发行者名称及导出说明更新为 **Siderfolio**；Python 包名 `astroagent`、`ASTROAGENT_*` 环境变量、数据库架构、会话 Cookie 与历史项目/快照归档格式保持兼容。
- **开发、CI 与发布流水线**：提供本机 `astroagent-v16` 按轮服务更新、按需隔离预览环境 `astroagent-dev`、科学计算与数据库覆盖门槛校验（`scripts/ci_verify.py`）及受控镜像构建清单工具（`scripts/release_assets.py`）。 [开发与发布手册](../../DEVELOPMENT_AND_RELEASE.md)

本机 Docker 部署可沿用现有 PostgreSQL、模型和私有配置更新。本版通过 GitHub Release 提供源码压缩包。 [发布复核](../../test-records/v2.0.0/release/20261123T113800Z/README.md)
