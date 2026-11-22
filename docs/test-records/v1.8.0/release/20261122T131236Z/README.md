# AstroAgent v1.8.0 发布复核

2026-11-22。以 `v1.7.0` 的 `b1c0cc4` 为基线。本次复核了增量验收记录与待发布源码，验收后只更新发布说明、索引与路线图。 [增量验收](../../changed-parts/20261122T082958Z/README.md) · [变更指纹](../../changed-parts/20261122T082958Z/tested-source.json) · [发布源码复核](source-verification.json)

| 核对项目 | 依据 |
| --- | --- |
| 离线、数据库和浏览器 | 后端 661 项、独立 PostgreSQL 66 项、真实隔离绘图 1 项、前端单元 47 项、Chromium 47 项通过。按运行条件跳过的项目详见增量验收记录。 |
| 真实天文查询与模拟 | AstroAgent 和独立 Inspector 查询 SIMBAD、ADS、Gaia 均成功。REBOUND 与 PeTar 各交付 129 帧双体样例。 |
| Docker 部署 | 本机已更新前端、后端和入口代理，登录页返回 `200`。沿用原 PostgreSQL、模型与执行容器。 |
| 正式发布 | 发布页列出同一提交在 `main` 和 `v1.8.0` 上的 GitHub Actions 运行。交付物为 GitHub 生成的源码压缩包。 [发布页](https://github.com/lct808846/astroagent/releases/tag/v1.8.0) |
