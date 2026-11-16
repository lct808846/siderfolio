# V1.6 账号与登录改动验收

结论：本次改动范围通过自动验收。范围为账号页、用户名与侧栏账号菜单、二维码绑定、两步邮箱登录、持久登录、来源校验及邮件入口关联行为。没有以此记录宣称整版重新验收或稳定版发布。

时间：2026-11-14。基线提交：`ea1eeec029dbf6d0cb35e12ee7526b1d7724b68b`；实际验收对象含未提交改动，以[source-manifest.json](source-manifest.json)的196个文件摘要固定。早期记录和本次失败均保留。

## 当前行为与用户确认

用户对登录入口的隐私行为差异回复“按照实际改动来”，因此按当前代码验收：

- 邮箱“继续”区分账号状态、是否需要动态验证码；不再宣称公开入口无法识别注册状态。
- 密码最短8、最长128；其余常见密码拒绝和摘要保护继续验证。
- 默认会话窗口为315360000秒，有效访问滚动续期；Cookie上限34560000秒。固定绝对寿命不续期不是本次通过条件；已过期、已撤销、禁用及来源异常仍须拒绝。

上述差异同步到[当前验收清单](../../../../development/v1.6.0/ACCEPTANCE.md)。

## 自动检查结果

| 检查 | 最终结果 | 证据 |
| --- | --- | --- |
| 前端相关单元测试，账号/二维码/会话请求 | 7通过，3个文件 | [unit-final.txt](unit-final.txt) |
| Python身份基础及安全边界 | 17通过 | [security-initial.xml](security-initial.xml) |
| 独立PostgreSQL身份集成及兼容测试 | 29通过，664项无关测试未选取 | [postgres-complete/tests.xml](postgres-complete/tests.xml) |
| 账号页、菜单、窄屏、退出状态清理，Chromium与Edge | 4通过 | [browser-final.json](browser-final.json) |
| 两步登录、邮件提示及跨站邮件入口关联回归，Chromium与Edge | 10通过 | [login-mail-browser-final.json](login-mail-browser-final.json) |
| 真实独立容器：登录、持久Cookie、页面跳转、来源头过滤、用户名保存和TOTP绑定，Chromium与Edge | 2通过 | [real-container-browser.json](real-container-browser.json) |
| 独立ZXing解码器核对二维码矩阵与完整URI | 3个样本精确匹配 | [qr-independent-decoding.json](qr-independent-decoding.json) |
| 独立解码实际浏览器渲染二维码图片 | 两浏览器均匹配预设测试密钥 | [qr-rendered-decoding-final.json](qr-rendered-decoding-final.json) |
| ESLint、TypeScript、Ruff、生产构建 | 通过 | [static-complete.json](static-complete.json)、[final-checks.json](final-checks.json)、[build.txt](build.txt) |

页面组件测试使用模拟接口，验证页面交互，不作为真实身份服务证明。真实容器测试使用5174独立入口和虚构账号；所有数据库集成使用临时独立数据库。上述类别存在交叉覆盖，不相加宣称唯一用例总数。

## 发现、修复与复验

1. 旧身份库缺少`auth_users.username`列，保存用户名会失败。`AuthStore.check()`增加幂等的新增列兼容处理；独立旧结构测试和真实容器用户名保存/刷新均通过。新增列不覆盖已有记录。
2. 初次数据库测试为26通过、2失败。一项是上述缺列问题；另一项仍断言旧固定绝对寿命，与当前持久登录行为不同。按用户确认改为验证有效会话续期且撤销不可复活，同时保留过期拒绝测试。最终完整身份集成为29通过。见[初次证据](postgres-initial/tests.xml)及[最终证据](postgres-complete/tests.xml)。
3. 初次账号页浏览器测试4项失败，原因是测试仍使用旧按钮文本、非唯一标签，且窄屏未打开侧栏。修正测试定位及操作步骤后4项通过，没有修改页面行为来迎合断言。见[browser-initial.json](browser-initial.json)。
4. 初次登录邮件浏览器测试8通过、2失败，测试错误地期待模拟接口原始文本；界面实际显示邮箱及本地化提示。改为核对目标邮箱、提示和重发冷却，最终10通过。见[初次证据](login-mail-browser.json)。
5. 真实容器首次两浏览器步骤均通过，但报告器因记录路径从错误目录解析而写入失败；改用绝对记录目录与新虚构账号，最终报告正常写入且2项通过。见[报告器初次结果](real-container-reporter-initial.json)。
6. 曾依据旧实现怀疑服务端页面跳转遗漏来源头；核对发现当前代码已包含转发处理，未重复修改。真实容器多次完整导航、刷新及伪造外部来源头检查均通过。

## 部署、数据与清理

- 更新日常后端前暂停后端并创建私有数据库备份；[backup-check.json](backup-check.json)只记录创建结果，不公布路径。本次未独立恢复这份备份，因此不将其称为恢复演练通过。
- 已将缺列兼容修复部署到日常后端。运行容器的100个相关后端、前端产物及入口文件摘要均与当前本地文件一致，见[deployment-comparison-final.json](deployment-comparison-final.json)。
- 独立QA容器与专属PostgreSQL、执行器账本卷已按项目标签核验后删除；共享模型卷保留，没有清空日常数据库、修改个人科研文件或更换认证/SMTP密钥。见[qa-cleanup.txt](qa-cleanup.txt)。
- 日常6个容器均健康。空闲时容器进程内存合计约431.5 MiB；这是一次瞬时采样，不包括Docker Desktop/WSL内核、宿主缓存、模型推理峰值或镜像磁盘占用，见[resources-final.jsonl](resources-final.jsonl)。
- 临时测试服务端口已关闭；公开记录扫描未发现当前私有配置凭据值，见[privacy-scan.json](privacy-scan.json)。

## 限制

本次未重跑无关科研检索、模型推理或绘图全流程；没有再次发送真实QQ邮件。二维码以独立软件解码和实际渲染图验证，未要求人工手机扫描，也不宣称对任意长度输入或全部二维码版本认证。运行环境仍是本机HTTP开发部署，公网HTTPS、跨机器、强对抗生产承载不在本次改动验收范围。未创建GitHub提交、标签或稳定版发布。
