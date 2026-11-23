# Siderfolio v2.0.0 发布复核

2026-11-23。以 `v1.8.0` 的 `d437730` 与 `v1.9.0` 的 `746d3be` 为基线。本次复核了 V1.9.0 + V2.0.0 联合验收记录与待发布源码，验收后只更新发布说明、索引与路线图。 [V2.0 联合验收](../../joint-acceptance/20261123T091033Z/README.md) · [V1.9 联合验收](../../../v1.9.0/joint-acceptance/20261123T091033Z/README.md) · [变更指纹](../../joint-acceptance/20261123T091033Z/tested-source.json) · [发布源码复核](source-verification.json)

| 核对项目 | 依据 |
| --- | --- |
| 离线、数据库和浏览器 | 后端离线 661 项、独立 PostgreSQL 与真实隔离绘图 91 项（0 跳过）、V1.9 离线评估 6 项、前端单元 47 项、Chromium 工作台 41 项与邮件导航 6 项通过。按运行条件跳过的项目详见联合验收记录。 |
| 多账号隔离、配额、恢复与双体基准 | 独立 PostgreSQL 验证 Agent `SavePermit` 直接入库、手动入库与幂等重放、重入库保留标签与备注、运行追踪脱敏与费用估算、跨账号 `404` 拒绝、单账号配额超限 `429` 隔离及 `pg_dump` / `pg_restore` 独立库完整恢复；REBOUND 与 PeTar 双体基准通过。 |
| Docker 部署 | 本机 `astroagent-v16` 已更新 `frontend` 与 `backend` 容器，7 个容器全部 `healthy`，登录页返回 `200`，匿名会话请求返回 `401 login_required`。沿用原 PostgreSQL、模型与执行容器。 |
| 正式发布 | 发布页列出同一提交在 `main` 和 `v2.0.0` 上的 GitHub Actions 运行。交付物为 GitHub 生成的源码压缩包。 [发布页](https://github.com/lct808846/astroagent/releases/tag/v2.0.0) |
