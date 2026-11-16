# V1.6 身份系统实施记录

日期：2026-11-14。源码版本：Python `1.6.0.dev0`、前端 `1.6.0-dev.0`。
实际代码基线：`ea1eeec`（V1.5 源码）。用户已有的 V1.6 开发文档与路线图变更保留。

**后续执行更新（2026-11-14）：已构建、自动测试并部署本机V1.6开发版；未发布V1.6稳定版。** 已配置真实SMTP与持久密钥。用户将迁移请求改为清空旧业务数据，备份恢复及完整内容核验后执行，未将旧数据自动分配给账号。新的事务提交校验会锁定并重新核对用户代次，防止运行中禁用/改密后的旧结果提交；独立端口部署使用认证配置中的精确origin。证据见[本轮记录](../../test-records/v1.6.0/acceptance/20261114T081737Z/README.md)。

以下关于“未执行”的文字描述初次开发阶段的历史状态，不能替代上述后续执行结果；V1.5验收证据仍不作为V1.6通过依据。

收尾静态检查：16个Python源文件语法解析、3个JSON解析、身份Compose覆盖文件YAML解析、两个Node代理文件语法解析均完成；词表100000行及固定SHA-256已核对。这些检查未加载应用、解析私有部署环境、启动服务或访问数据库，不是运行时测试/构建/验收结果。

## 源码范围

| 范围 | 实现位置 | 行为 |
| --- | --- | --- |
| 身份配置与密码 | `auth_config.py`、`auth_security.py` | 固定可信 origin；Argon2id；NFC 规范化；15–128字符；离线常见密码拒绝词表；不强制字符组合 |
| 控制平面 | `auth_store.py` | 独立 `public.auth_*` 账号、摘要令牌、会话、TOTP、恢复码、限流、退避、审计、加密发件箱 |
| 邮箱身份流程 | `api/auth.py` | 邮箱注册→POST确认→短期设密凭据→原子激活；登录、退出、重发、找回、改密、会话列表与全部退出 |
| 邮件工作器 | `auth_mail.py` | 加密且事务提交的发件箱，SMTP TLS/STARTTLS认证，持久租约、限额及有界重试；不公开邮件内容 |
| 默认鉴权 | `auth_access.py` | 默认拒绝匿名业务，认证体16KiB上限，CSRF与Origin，管理员/TOTP/近期重新认证，响应及下载块前再次验证撤销 |
| 业务隔离 | `identity.py`、`postgres.py` | 按账号组合独立仓储、服务图、后台工作器、RAG缓存和产物缓存；不同用户从SQL查询入口即隔离 |
| 管理接口 | `api/admin.py` | 脱敏用户分页、启禁用/角色、最后有效管理员保护、邮件重试与脱敏审计；不读取科研内容 |
| 前端 | `IdentityRoot.vue`及三个身份工作区 | 登录守卫、注册激活、账号安全、TOTP绑定及恢复码、手输网址管理页；主站无后台入口 |
| HTTP与缓存 | `session-http.ts`、`identity-state.ts` | Cookie只在HttpOnly中；CSRF仅内存；上传/下载同样受保护；换账号/退出丢弃应用状态及本站私有偏好缓存 |
| 本机维护 | `identity_cli.py`、`scripts/identity_backup.py` | 首位管理员、TOTP离线恢复、备份与旧数据认领；默认预览，写入须显式确认 |
| 容器 | `compose.identity.yaml`、入口脚本 | 独立V1.6镜像标签、认证秘密文件、内部健康探针；保留回环发布与既有绘图执行器边界 |

## M0：访问与资源归属清单

所有业务入口先经过 `IdentityAccess`，包括原 `/api/v1/chat`、附件解析、科学ZIP导出、模型目录和下列有状态入口。

| 业务 | 表或介质 | 归属校验方式 |
| --- | --- | --- |
| 会话与轮次 | conversations、turns | 当前用户私有schema；资源和轮次关联仍由原仓储核对 |
| 项目与快照 | projects、project_conversations、snapshots、reruns、imported_turn_origins | 同一私有schema；跨用户ID查询不到父对象 |
| 科研流程 | workflows、workflow_operations、workflow_outputs、workflow_snapshot_refs | 私有schema及原有父子引用检查 |
| 文献 | knowledge_documents/versions/sources/units/evidence/operations | 文件与段落在本人schema，检索前限定该namespace和项目 |
| 来源关联 | project_links、project_link_requests | 两端资源均从本人schema取回 |
| RAG | rag_indexes/active/vectors/previews/answers/answer_requests | 向量和词法SQL从本人schema运行；每个用户独立服务缓存 |
| 绘图 | plot_meta/datasets/operations/outputs | 数据与文件BLOB在本人schema；执行器产物只能由本人的操作记录读取 |
| 本地助手 | local_assistant_meta/tasks | 用户独立的偏好、队列、任务、结果缓存；自动命名只操作本人会话 |
| 临时附件与科学导出 | 请求内容/用户服务内存 | 不提供跨账号全局文件查询；导出、下载仍需有效Cookie |
| 系统设置/OpenAPI | 运维信息 | 管理员且完成TOTP才可读取；Swagger/ReDoc默认关闭 |

匿名白名单仅包含 `/api/v1/auth/csrf`、身份状态读取和注册/确认/登录/找回所需POST。身份状态在没有登录时仍返回401，不返回用户资料。其余身份操作也需登录。WebSocket未提供业务功能，统一关闭，避免将来隐式放行。

## 命名空间方案

本版选择每用户一个 PostgreSQL schema，而不是逐表增加owner字段。命名为服务器生成的 `aa_<32位十六进制>`，映射在 `auth_users`，前端不提交、不选择该值。

仓储连接的 `search_path` 只有这个私有schema。PostgreSQL隐式查找pg_catalog；**不回退public业务表**。pgvector类型、操作符、维度函数与pg_trgm操作类显式限定到public中的已安装扩展；身份表使用全限定名。用户不能提交任意业务SQL，也不能创建函数或指定搜索路径。

首次访问本人业务时，只在本人的空namespace创建业务表；不对public旧表初始化、修复、自动归属或回退。由同一服务端数据库角色维护这些schema，属于应用强制隔离，不宣称抵御服务端数据库凭据泄露或任意SQL执行；后续安全验收必须覆盖全部入口，不能以schema命名代替证据。

用户禁用、角色改变会撤销其会话、递增业务访问代次并失效旧服务图。旧任务不能用过期代次提交结果，重新启用后的服务按原恢复机制将未完成记录标成中断，不自动重发。密码重置、改密、TOTP重绑同样更新代次。已开始的外部计算可能直到超时才结束；当前策略是阻止后续写入和结果读取，不宣称能够取消供应商计算。

## 会话与邮件约定

- Cookie为浏览器会话Cookie，生产 `Secure + HttpOnly + SameSite=Lax`；本地HTTP必须明确开启local_http，不能用于远程域名。
- 空闲默认30分钟、绝对默认12小时；服务端会话摘要可撤销。令牌不进入localStorage。
- CSRF使用HttpOnly预认证随机Cookie/已登录Cookie与服务端密钥派生的内存token，写操作同时核对固定Origin。不提供跨源携凭据模式。
- 登录按来源与邮箱分别限流，并在失败后指数退避；重复失败进入脱敏审计。入口覆盖客户端伪造的来源头，前端仅信任内部ingress解析到的连接地址，后端仅在私有proxy凭据通过后读取经校验的来源。不会盲信公网X-Forwarded-For；额外TLS反代尚未明确信任时按保守来源限额处理。
- 管理操作要求管理员、TOTP会话和5分钟内的密码+验证码重新认证；登录时可使用一次性恢复码。
- 邮件令牌表仅存摘要；需发送的明文链接只存在加密发件箱，发信提交后清除密文正文。TOTP密钥也加密，恢复码只存摘要。
- 发件箱状态为pending/sending/submitted/failed/cancelled，最多5次尝试，管理员可限频重试。SMTP在提交后、写回状态前崩溃可能重复投递同一Message-ID；同一链接仍一次性。**不承诺SMTP恰好一次或收件箱送达。**
- 公开响应不区分账号存在、未激活或禁用。邮件未配置时注册/重发/找回不可用，已有账号仍可登录；不会跳过验证。
- 审计默认保留90天；不记录密码、Cookie、令牌、邮件正文或科研内容。后台邮箱只显示脱敏形式。

## 依赖与准备状态

新增固定身份依赖：argon2-cffi 25.1.0、bindings 25.1.0、email-validator 2.3.0、dnspython 2.8.0；沿用已锁定cryptography 46.0.3。仅更新依赖声明，没有安装或构建验证。

离线词表已从SecLists官方仓库下载到 `src/astroagent/auth_data`，781879字节，SHA-256 `1472aafa2561df5e3293aee252aee3ca660c12b399a283cf808bb01b39be388b`，附MIT许可证及来源说明。它不是完整泄露密码库，可由运维换成更大已审核词表；用户密码不发往外部词表服务。

已有业务OpenAPI/TypeScript快照保留为V1.5业务契约；新的身份客户端单独声明类型，运行时OpenAPI由FastAPI实际路由生成。发布验收时需重新生成完整快照并检查差异。

## 未执行与下一步

没有运行单元测试、Ruff/ESLint检查、类型检查、生产构建、浏览器、SMTP/模型调用、Docker命令或个人库迁移。静态语法检查不证明授权、并发、迁移或前端行为正确。

部署与维护见[操作说明](OPERATIONS.md)，待验收项见[验收清单](ACCEPTANCE.md)。进入使用前还需要配置私有认证密钥及真实SMTP、在隔离库初始化并验证两账号隔离/邮件/管理/迁移。不能直接用这份源码替换运行中的V1.5后再猜测历史数据归属。

参考：[OWASP密码存储](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)、[会话管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)、[NIST认证器指南](https://pages.nist.gov/800-63-4/sp800-63b.html)、[PostgreSQL命名空间](https://www.postgresql.org/docs/current/ddl-schemas.html)。这些设计参考不构成本项目通过安全认证的声明。
