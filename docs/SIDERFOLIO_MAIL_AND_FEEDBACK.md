# Siderfolio 域名邮件与用户反馈

## 邮件地址

| 地址 | 用途 | 服务 |
| --- | --- | --- |
| `noreply@siderfolio.com` | 注册验证、密码重置、安全通知、反馈通知 | Resend SMTP 发件身份 |
| `admin@siderfolio.com` | 管理与运维收信 | Cloudflare Email Routing 转发 |
| `support@siderfolio.com` | 技术支持、反馈与 Bug 报告收信 | Cloudflare Email Routing 转发 |

两条收件规则指向已验证的个人邮箱。Catch-all 保持关闭。Resend 使用东京区域，仅启用发信，关闭发件追踪。普通回复仍通过浏览器内的反馈详情显示。 [Cloudflare 转发文档](https://developers.cloudflare.com/email-service/get-started/route-emails/) · [Resend 域名配置](https://resend.com/docs/dashboard/domains/introduction)

2026 年 11 月 24 日已核对两条 Cloudflare 转发规则均为活跃，Resend 发信域及其三条 DNS 记录均为 Verified。公开 DNS 已返回表中的 MX、SPF、DKIM、DMARC 和 CNAME。发布前从 Resend 的 HTTPS 接口向两个收件地址实发各一封，目标 QQ 邮箱确认均已收到。

## DNS 与发件配置

| 记录 | 用途 |
| --- | --- |
| `@` MX | Cloudflare 自动配置 `route1`、`route2`、`route3.mx.cloudflare.net` 及对应优先级 |
| `@` TXT | 唯一 SPF 为 `v=spf1 include:_spf.mx.cloudflare.net -all` |
| `cf2024-1._domainkey` TXT | Cloudflare 转发 DKIM，由控制台管理 |
| `resend._domainkey` TXT | Resend 发信 DKIM，公钥取自该域名的设置页 |
| `rsend`、`send` CNAME | Resend 提供的发信认证与退信别名，保持仅 DNS |
| `_dmarc` TXT | 沿用 `v=DMARC1; p=reject; sp=none`，正式发信前确认 SPF 或 DKIM 与 From 域对齐 |

Cloudflare Email Routing 提供免费转发。Cloudflare 的独立 Email Sending 支持 SMTP，但向未预先验证的普通用户外发需要 Workers Paid。Resend 免费方案包含每 UTC 日 100 封、每月 3,000 封，并支持项目现成的加密 SMTP。Brevo 免费方案每日 300 封，也兼容现成 SMTP，需要另外完成发信域验证。当前方案沿用原有邮件队列。 [Cloudflare Email Service 定价](https://developers.cloudflare.com/email-service/platform/pricing/) · [Resend 额度](https://resend.com/docs/knowledge-base/account-quotas-and-limits) · [Brevo 免费方案](https://help.brevo.com/hc/en-us/articles/208589409-About-Brevo-s-pricing-plans)

运营人员在 Resend 创建仅用于此域发信的密钥。在已获批准的环境中，通过私有部署配置填入 SMTP 密钥。应用不会调整服务商计划。 [Resend SMTP](https://resend.com/docs/send-with-smtp)

本机实测 Resend 的备用端口 2465（TLS）和 2587（STARTTLS）可完成加密认证。本机私有配置采用 2465。生产切换前从 GCP 核对实际端口的连通性和 TLS，按结果选择端口与对应模式。

```dotenv
SMTP_HOST=smtp.resend.com
SMTP_PORT=2465
SMTP_MODE=tls
SMTP_USER=resend
SMTP_PASSWORD=''
SMTP_FROM=noreply@siderfolio.com
MAIL_HOUR_LIMIT=100
MAIL_DAY_LIMIT=90
MAIL_MONTH_LIMIT=2700
```

注册、找回和安全通知沿用服务端 `SMTP_FROM`。反馈队列仅在正式域名发件配置就绪时发送，通知正文只包含编号和站内登录链接。开发预览可在邮件未配置时提交和查看反馈。

验证邮件每次签发至少间隔 60 秒。注册、重发与找回共用每小时阈值，另按邮箱每日 8 次、来源 IP 每日 20 次限制邮件请求。每个来源 IP 每日最多新建 5 个账号，同时遵循现有注册容量。全站发送按 UTC 小时、日、月限额，SMTP 尝试计入限额，达到 80% 时在管理后台和服务日志提示。达到限额后队列等待重置，过期令牌须重新申请。服务商的实际用量以其控制台为准。

## 反馈与本地迁移

用户从查询工作台的账号菜单进入「帮助与反馈」，提交类型、标题、描述和一张可选截图，并查看自己的历史与管理员回复。控制台的「用户反馈管理」支持按类型、状态和日期筛选，已重新认证的管理员可变更状态和回复。

PostgreSQL 保存反馈和回复。截图复用 Pillow，校验格式、像素和体积后重新编码为 PNG，移除图像元数据。截图接口继承会话认证与禁止缓存策略。每个账号每日最多提交 5 次，每个来源 IP 每日最多 20 次。用户提供的标题、描述和回复均按纯文本渲染。

用户 API 是 `/api/v1/feedback`。管理 API 是 `/api/v1/admin/feedback`，邮件配额 API 是 `/api/v1/admin/mail/usage`。反馈迁移只新增两张表、索引和版本标记。

在本机开发栈中应用增量迁移。脚本先检查数据库归属，重复执行只返回已安装状态。

```powershell
.\scripts\dev.ps1 -Action Update
.\scripts\dev.ps1 -Action InitFeedback
```

生产迁移与生产 SMTP 切换分别取得授权。更新代码后，在经核对的生产后端容器里执行 `python -m astroagent.identity_cli install-feedback`。已初始化的数据库使用此增量命令，空库才按现有首次部署流程初始化。

## 发布前核验

1. 核对 `admin` 与 `support` 的转发结果和 Catch-all 状态。首次验收已确认两条规则均可投递至目标 QQ 邮箱。
2. 切换前从生产主机核对 SMTP 端口与 TLS。切换后，经授权使用专用测试账号检查注册、找回、安全通知和反馈提交的实际邮件，在收件端核对 SPF、DKIM、DMARC 及正式域名链接。通过站内反馈详情检查管理员回复。
3. 验证跨账号读取、截图越权、管理员权限、并发重发、每日与全局配额，以及 SMTP 失败时反馈是否仍然可见。
4. 检查桌面、窄屏、浅色和深色下的表单、列表、截图和回复。检查账号与已有科研功能启动健康。
