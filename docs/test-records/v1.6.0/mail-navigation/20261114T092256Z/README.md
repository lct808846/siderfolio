# 邮件链接跨站导航修复

日期：2026-11-14。用户从QQ邮箱打开激活链接时，前端返回 `Unsupported request origin`。原入口对所有 `Sec-Fetch-Site: cross-site` 请求直接403，误伤了浏览器从邮箱跳转的正常顶层GET导航。此前验收使用直接访问页面，遗漏了这个实际入口场景。

修复仅在以下条件同时满足时允许跨站读取：GET/HEAD、精确匹配身份公开页面白名单、`Sec-Fetch-Mode: navigate`、`Sec-Fetch-Dest: document`。激活和重置仍需用户主动提交；后台身份、Origin、CSRF与一次性令牌校验没有改变。跨站API、私有页面、POST、iframe、图片和fetch仍拒绝。

`browser-final.json/txt`：Chromium与Edge共6项通过。浏览器在localhost模拟邮箱点击127.0.0.1站点链接，真实请求头确认为cross-site；激活页面可打开，GET不提交令牌，点击主动确认后出现设密表单；重置链接只打开表单，不修改密码。另验证全部公开身份页GET/HEAD及跨站拒绝矩阵。测试只使用独立HTTP夹具与虚构令牌，不访问个人数据库，不打开、记录或消费用户真实邮件令牌。

`browser-first.json/txt`保留首次2项失败：页面实际上已显示设密表单，但测试使用精确标签“新密码”，未考虑同一label包含密码说明文字。修正匹配后复验通过，没有为此改动产品行为。

`frontend-checks.json`的ESLint/类型检查成功，`frontend-container-build.txt`记录生产镜像构建成功。仅重建、替换前端容器，后端、数据库、模型和认证密钥未修改。`deployed-ingress-check.json`在实际5173入口确认公开邮件导航200，跨站API和确认POST仍403。`source-identity.json`核对容器中server.mjs与本地修复源码哈希一致。

对应回归命令已加入前端CI。当前工作区尚未提交/推送，本记录不宣称远程CI已运行，也不属于稳定版发布。用户可刷新原失败页面或重新点击邮件链接继续；若随后确实过期，应使用重发激活邮件流程。
