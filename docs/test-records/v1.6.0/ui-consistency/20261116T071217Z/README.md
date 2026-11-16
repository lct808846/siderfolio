# 个人资料与相关布局视觉记录

日期：2026-11-16。对应[增量验收与源码摘要](../../changed-parts/20261116T071217Z/README.md)，截图均为虚构账号和合成业务数据。

- [个人资料桌面](chromium-profile-desktop.png)
- [Chromium 320px 个人资料](chromium-profile-mobile.png)
- [Edge 320px 个人资料](edge-profile-mobile.png)
- [Chromium 上传失败状态](chromium-profile-upload-error.png)
- [Edge 上传失败状态](edge-profile-upload-error.png)
- [查询侧栏与结果区](chromium-full.png)
- [项目窄屏](edge-project-mobile.png)

初始个人资料截图发现内部裁切：根页面宽度正常，但名称与时间超出阅读区。已修复个人资料网格、按钮文字和元数据的收缩/换行；复验增加内部元素边界断言，避免只看根页面宽度而漏掉裁切。

个人资料自动检查 1440、1280、1024、981、980、768、390、320 CSS px，覆盖侧栏切换、草稿保持、用户名键盘取消/提交、头像替换/移除、输入超限和服务端拒绝。缺失 Token 显示“—”，错误后仍可重试，不出现虚假的已上传状态。

共享布局的查询、项目、文献、来源关联、流程、设置与绘图确认有双浏览器相关回归；既有低高度、强制颜色与减少动态效果用例通过。仅核对所列代表页面、尺寸及状态；未认证全部 CSS 取值、系统级缩放、浏览器扩展或完整无障碍标准。未要求用户执行人工验收。
