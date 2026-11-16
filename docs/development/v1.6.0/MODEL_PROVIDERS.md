# V1.6 模型服务商管理

2026-11-15：设置分类“回答模型”更名为“模型”，沿用现有设置导航、主题变量、通知、错误提示和原生对话框。

## 使用流程

管理员进入“设置 → 模型”，添加模型服务商，填写显示名称、公共 HTTPS API 根地址和 API 密钥。本地助手和嵌入模型仍由各自分类维护。

| 协议 | 根地址示例 | 实际请求 |
| --- | --- | --- |
| OpenAI Chat Completions | `https://api.example.com/v1` | `/chat/completions` |
| OpenAI Responses | `https://api.openai.com/v1` | `/responses` |
| Anthropic Messages | `https://api.anthropic.com/v1` | `/messages` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta` | `/models/{model}:generateContent` |

填写根地址即可，不填写具体请求路径。Anthropic 使用 `x-api-key` 和兼容版本 `2023-06-01`，Gemini 使用 `x-goog-api-key`；密钥不拼接到 URL。协议决定请求、工具回传、目录解析及完成状态处理，不自动试用其他协议或重发付费请求。

- 可以编辑、启用、停用和删除服务商；密钥留空保留旧值，更改 API 地址或协议须重新输入密钥。
- “获取可用模型”显式请求此服务商的 `/models` 目录，提供搜索、多选与列表更新；目录不受支持时可手动添加模型 ID 和显示名称。Gemini 目录只纳入支持 `generateContent` 的模型；服务商返回分页标记或超出本次展示上限时，界面说明本次目录不完整，可以手动补充。
- 每个服务商最多 32 个模型，共 16 个服务商、总计 256 个模型。目录返回最多展示 512 个有效模型，响应上限 1 MiB。
- 可设置已启用模型为默认。停用或删除默认模型的服务商时，选择首个剩余可用模型；没有可用模型时提示未配置。
- 配置为共享设置，由已完成登录 MFA 的管理员维护。按用户后续要求，模型配置保存、删除、默认选择及目录读取不再要求五分钟内密码和 MFA 再认证。保留登录、管理员、有效 MFA 会话、CSRF、限流及写入时的数据库权限核对；其他管理操作的重新认证要求保持原状。

API 协议和思考参数使用共用 SettingsSelect 菜单，沿用主题表面、边框、圆角与滚动条；选中项勾选、协议说明、方向键和首字母定位、Escape 关闭、焦点返回、菜单空间定位与减少动态效果均在组件内维护。菜单以原生 popover 顶层展示，避免被编辑弹窗的滚动区域裁切；关闭不占布局空间。

## 现有配置与数据

第一次读取时，将已有环境中的模型服务呈现为“现有模型服务”，保留原模型 ID。只有管理员显式保存时才写入配置；打开页面、构建及部署均不修改模型密钥或默认模型。

服务商配置使用现有身份密钥加密，存入现有 `public.auth_meta` 的 `model_providers_v1` 元数据项，不新增表、不迁移业务数据。备份应包含该元数据与原有身份密钥；二者缺一不可恢复密钥。列表只返回密钥是否配置，不返回密钥内容，浏览器持久存储中不保存密钥。

配置更新在管理员写入锁内执行，并检查修订号；过时的编辑需刷新后重试。服务商删除保留已有会话、回答与科研记录，但该服务商的模型不能继续用于新请求。

## 与科研工作台联动

查询、绘图规划与文献问答均通过服务端模型目录解析所选服务商。新服务商使用稳定的服务商与模型组合标识，避免不同服务商相同模型 ID 相互覆盖；界面显示模型名称并按服务商分组。切换保留现有会话历史，不创建新会话。

文献问答预览保留所选组合标识和实际服务地址、模型及协议指纹，确认生成时重新核对配置。上传、索引及打开设置不调用回答模型。科研查询与绘图需要模型支持工具调用，文献问答需要兼容结构化回答；目录获取成功不代表这些能力已经通过验收。

多协议适配复用现有有界工具调用循环、参数校验与科研来源记录。Responses 保留本轮原始输出项与加密推理内容，Anthropic 保留消息内容块和工具 ID，Gemini 保留原始 Part、thoughtSignature 及函数回传关联。未完整生成的新增协议响应不执行工具、不展示为完整回答。文献问答统一按真实上游模型 ID 请求，仍检查完成状态、JSON 格式、证据标签及引用范围。

接口参考：[OpenAI 函数调用](https://developers.openai.com/api/docs/guides/function-calling)、[OpenAI 无状态推理](https://developers.openai.com/api/docs/guides/reasoning)、[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create)、[Anthropic 版本兼容](https://platform.claude.com/docs/en/api/versioning)、[Gemini generateContent](https://aistudio.google.com/api-reference/generate-content)。

## 验证边界

### Gemini 402 计费错误定位与提示修正（2026-11-15）

用户截图中的 `gemini-4-hydrogen` 请求失败原先统一显示 `model_unavailable`，误导为 API 协议或地址问题。经用户单独授权，使用已配置服务商进行了一次有界诊断请求，没有创建会话或修改配置。Google 返回 HTTP 402、`RESOURCE_EXHAUSTED`，明确提示预付费 credits 已耗尽；没有返回模型候选内容。诊断只输出脱敏状态与错误，不记录密钥。

新增协议客户端对上游非 200 响应最多读取 64 KiB 后分类：Gemini 402 显示 `gemini_billing_required` 和项目余额／结算说明；其他 402、鉴权、限额、模型不存在和参数错误各用明确类别。上游原始错误、URL、请求头或密钥不透传，只记录协议、HTTP 状态和固定错误类别。计费错误不标为可自动重试。

页面为 Gemini 计费错误提供官方结算入口。保留历史失败记录，不将单次诊断结果写成已有会话的错误原因。当前故障需要用户在对应 Google 项目补足预付费余额后重试；软件更新不能恢复外部服务额度。没有追加第二次真实模型请求，也没有进行充值或其他计费变更。

参考：[Google 预付费余额与 HTTP 402 说明](https://aistudio.google.com/docs/billing#prepay)。构建及容器健康通过不代表生成成功。

### API 密钥输入与浏览器密码保存（2026-11-15）

原先 `type=password` 与 `autocomplete=new-password` 会使浏览器把服务地址和 API 密钥识别为一组新登录凭据，甚至在获取目录时提示保存密码。密钥字段现根据浏览器能力使用普通文本控件，并通过 `-webkit-text-security: disc` 遮挡字符，不将其标记为登录密码。表单及字段关闭自动填充，字段关闭拼写检查、自动大写与自动纠正，并提供密码管理扩展忽略提示。

当前 Edge/Chromium 使用上述遮挡文本模式；不支持该 CSS 属性的浏览器回退到原生密码遮挡，优先避免明文显示。网站无法强制关闭浏览器或扩展的自主密码管理行为，回退环境仍可能有提示。保持原来的密钥清空时机与服务端加密存储流程，未改变账号登录页面的密码保存行为。

参考：[MDN 文字遮挡属性](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/-webkit-text-security)、[MDN 自动填充属性](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/autocomplete)。本次仅构建并更新前端容器，浏览器实际提示行为待用户验收。

### 本机代理 Fake-IP 兼容修正（2026-11-15）

实际后端 DNS 将现有服务域名解析为 `198.18.1.62` 和 `2001:2::14c`；原先仅允许 `is_global` 的目录校验在 HTTP 请求前拦截了这些地址。修正为：仅当服务端显式启用身份系统的 loopback 本机模式 `local_http` 时，额外允许域名解析落入 `198.18.0.0/15` 与 `2001:2::/48` 两个代理虚拟地址范围。远程站点模式继续只接受公网解析地址，不额外放行。

仍要求 HTTPS 根地址、原域名 TLS 证书校验及禁止重定向；不改写域名为 IP，不修改代理设置，不绕过证书验证，不允许填写 Fake-IP 字面地址。回环、链路本地、RFC1918、IPv6 ULA、组播与未指定地址继续阻止。受限地址提示改为说明 DNS／代理解析问题，避免误导为没有填写 HTTPS。

代理 DNS 配置参考：[Mihomo DNS 文档](https://wiki.metacubex.one/config/dns/)。仅修正已确认的请求前拦截，不据此宣称服务商鉴权、连通或模型调用验收通过。

接口快照与前端类型通过已有后端镜像离线生成。部署执行生产构建内置类型检查、依赖检查及相关容器启动健康检查；按用户约定未运行自动测试、浏览器验收或真实模型请求，未实际提交任何新的服务商密钥。
