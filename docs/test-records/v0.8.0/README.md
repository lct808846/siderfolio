# V0.8.0 验收记录

记录说明：早期测试基线为 `9b16fe9523eea826aa5c36f42c24cce384004ed2`；远程 main 后来前进，本地已快进到 `4c38c3376c737ab380219b837e7b0b7a49208dff`。这些工作区测试不能代替目标提交的远程 CI；发布状态以 GitHub Releases 为准。测试使用合成数据、公开论文和临时数据库。

同步远程 main 后的结果：

- [最新 Windows 完整离线回归](offline-tests/20261030T114207368126Z/report.json)：491 项通过、19 项按条件跳过；15 项真实联网、2 项 Linux 资源、公开 PDF 和 256 MiB 大容量用例均已单独执行，记录见下。Ruff、格式与依赖检查通过。
- [最新 Ubuntu 完整离线回归](offline-tests/20261030T114214129849Z/report.json)：490 项通过、20 项按条件跳过；Python 3.14.4，Ruff、格式与依赖检查通过。跳过项为联网、Windows 专项、公开 PDF 和大容量显式验收，均有单独记录。
- [真实混合损坏 PDF、公开 PDF 全页及 256 MiB 检查](pdf-storage-tests/20261030T114120Z/pytest.xml)：Windows 3 项通过；[Ubuntu](linux-tests/20261030T113600Z/pytest.xml) 中真实混合损坏 PDF 和 256 MiB 合成 BLOB 检查 2 项通过。公开 PDF 的 14 页已检查 API 文本与哈希、浏览页面版式，未逐字证明公式或图表提取正确。初次损坏页构造被 pypdf 当作空页，改用实际损坏文本流后通过。
- [最新 Windows 离线回归](offline-tests/20261030T112745274488Z/report.json)：490 项通过、18 项按条件跳过；新增历史分段变化不得重定向旧引用的用例，并在 [Ubuntu](linux-tests/20261030T112800Z/pytest.xml) 单独复验通过。
- [最新浏览器回归](browser-tests/20261030T112527691722Z/report.json)：Chromium 与 Edge 共 24 项通过；包含公开 PDF 和 390 像素长中文文件名。两张长文件名截图已人工核看。此前 [长文件名测试失败记录](browser-tests/20261030T112307253795Z/report.json) 保留，原因是上传后界面自动切到检索面板而测试未切回。
- [包含独立目录恢复的 Windows 离线检查](offline-tests/20261030T111614764240Z/report.json)：489 项通过、18 项按条件跳过；其中 schema3 备份恢复已在 [Ubuntu](linux-tests/20261030T093000Z/pytest.xml) 单独复验。
- [最新 Windows 离线检查](offline-tests/20261030T092000166350Z/report.json)：488 项通过、18 项按条件跳过，包含归档原文位置及引用篡改测试。
- [SIMBAD 与模型](live-tests/20261030T092033713134Z/report.json) 2 项、[ADS](live-ads-tests/20261030T092211432986Z/report.json) 6 项、[Gaia](live-gaia-tests/20261030T092320947455Z/report.json) 7 项均通过；对这三组记录检查当前凭证明文匹配数为零。
- [Windows 离线检查](offline-tests/20261030T091131280725Z/report.json)：483 项通过、18 项按条件跳过，Ruff、格式和依赖检查通过。
- [最新 Windows 离线检查](offline-tests/20261030T091522875170Z/report.json)：485 项通过、18 项按条件跳过，包含新增的 PDF 提取文本上限和 Markdown 混合换行定位测试。新增的两项也在 [Ubuntu](linux-tests/20261030T091700Z/pytest.xml) 通过。
- [加入 multipart 传输边界后的 Windows 离线检查](offline-tests/20261030T091743936318Z/report.json)：486 项通过、18 项按条件跳过，Ruff、格式与依赖检查通过。
- [Ubuntu 离线检查](offline-tests/20261030T091132521370Z/report.json)：482 项通过、19 项按条件跳过，Ruff、格式和依赖检查通过；Python 版本为 3.14.4。
- [Chromium / Edge 浏览器检查](browser-tests/20261030T091130352716Z/report.json)：22 项通过，含公开 PDF 上传、引用、受限预览与下载核对。
- [Windows 项目 HTTP 回归](acceptance-v06/20261030T091256164813Z/report.json)及[独立 wheel 检查](release-audit/20261030T091256108707Z/report.json)通过。

- [合成检索评估](knowledge-evaluation/20261030T013900043889Z/report.json)：24 条正例前五覆盖率 1.0，8 条无答案拒答率 1.0，无效引用 0，P95 约 0.028 秒；不代表真实文库表现。
- `pytest tests/test_knowledge.py -q`：Windows 本机 6 项通过，涵盖合成 Markdown、PDF、旧引用、归档、项目隔离、schema3→4、迁移回滚及子进程超时和保护失效处理。此直接运行没有独立 JSON 报告。
- [前端检查](frontend-tests/20261030T050100243789Z/report.json)：类型、lint、15 项单元测试、构建和 OpenAPI 类型一致性通过。
- [完整离线检查](offline-tests/20261030T050100421988Z/report.json)：454 项通过、15 项跳过，Ruff 检查、格式及依赖检查通过。超时测试运行超过 pytest 的 30 秒堆栈提示阈值，最终按预期通过。
- [补充测试后的离线检查](offline-tests/20261030T051310083518Z/report.json)：460 项通过、16 项跳过；跳过的 15 项联网测试已单独运行，另 1 项是须显式提供公开 PDF 的检查，已单独运行。包含 schema1、2 升级和高版本拒绝测试。
- [Ubuntu 完整离线检查](offline-tests/20261030T084534379499Z/report.json)：Python 3.14.4 下 465 项通过、18 项跳过，Ruff、格式和依赖检查通过；运行启动后又增加的旧版本恢复测试已在 Windows 单独通过。
- [最新 Windows 离线检查](offline-tests/20261030T084756902474Z/report.json)：466 项通过、18 项跳过，Ruff、格式和依赖检查通过；15 项联网测试、2 项 Linux 资源限制和公开 PDF 测试已分别运行，见下方记录。
- [补充边界后的 Windows 离线检查](offline-tests/20261030T090630606771Z/report.json)：481 项通过、18 项跳过；报告包含文档、版本、操作、引用和候选扫描上限、格式3坏包及事务故障测试。Ruff、格式和依赖检查通过。
- [补充后的 Ubuntu 知识库专项](linux-tests/20261030T091000Z/pytest.xml)：32 项通过、3 项跳过（两项 Windows Job Object 检查及须显式提供的公开 PDF）；实际运行日志见 [transcript](linux-tests/20261030T091000Z/transcript.txt)。
- [串行浏览器检查](browser-tests/20261030T050143577480Z/report.json)：Chromium 和 Edge 共 20 项通过，临时服务端口已关闭；知识库窄屏截图已查看，其余人工视觉检查仍待完成。
- [公开 PDF 与边界检查](knowledge-acceptance/20261030T051300Z/README.md)：公开论文首页、原始字节、检索定位，超大上传拒绝和篡改备份的原子拒绝共 3 项通过；不代表所有 PDF 或边界已验证。
- [公开 PDF 浏览器验收](browser-tests/20261030T090713169559Z/report.json)：Chromium 与 Edge 共 22 项通过，包括 PDF 引用打开受限预览、下载内容与原文件逐字节一致，完整原文归档确认与仅元数据下载。临时端口已关闭；视觉验收仍需按清单覆盖其余界面。
- 边界测试使用临时库模拟已达到 100 文档、200 版本、500 操作、1000 引用及 256 MiB 预留配额，确认拒绝且不覆盖原文件；候选扫描超过 20 MiB 被拒，分段函数在 25000 和 25001 项分别验证。格式3归档验证错误归属、非有限数、路径、重复/未知成员及导入中途故障回滚。
- 纯图像合成 PDF 明确返回 `knowledge_no_text`、不执行 OCR；初次单项测试错误地期望 HTTP 201，后按现有契约改为检查 HTTP 422 并重跑通过。混合页面提取失败用替身模拟，不代表某个真实损坏 PDF 的验证。
- [真实 SIMBAD 与模型](live-tests/20261030T050658788287Z/report.json)：2 项通过；30 秒堆栈提示为测试诊断，最终结果通过。
- [真实 ADS](live-ads-tests/20261030T050903940776Z/report.json)：6 项通过；[真实 Gaia](live-gaia-tests/20261030T051012696370Z/report.json)：7 项通过。运行中产生的 30 秒堆栈是诊断输出，最终以测试结果为准；对三组记录检查当前凭证的明文匹配数为零。
- [PDF 页数及 Markdown 行数上限等专项复测](knowledge-acceptance/20261030T051500Z/pytest.xml)：4 项通过，超限文档标记失败且不可检索。
- [项目 HTTP 回归首次运行](acceptance-v06/20261030T051028239593Z/report.json)：业务检查通过，但两次停止后的端口监听核验未通过，故报告整体失败；事后该端口查询无监听，不能据此更改原报告。
- [项目 HTTP 回归第二次运行](acceptance-v06/20261030T051327657730Z/report.json)：业务检查通过，端口监听核验仍失败，整体失败。
- [项目 HTTP 回归第三次运行](acceptance-v06/20261030T051433956790Z/report.json)：业务检查通过；增加有界等待后仍有一次监听核验未通过，整体失败。四个验收进程随后确认均已退出；监听表查询结果不一致，原因未确认。
- [Windows 项目 HTTP 回归](acceptance-v06/20261030T085742254366Z/report.json)：20 项业务检查通过，四次进程与端口清理均通过。旧检测的 PID 0 条目见 [诊断报告](acceptance-v06/20261030T085445383192Z/report.json)；新版使用 Windows IP Helper 原生 IPv4 监听表，并有实际打开、连接和关闭本地套接字的回归测试。此前失败记录保留。
- [Linux 项目 HTTP 回归](acceptance-v06/20261030T084201970516Z/report.json)：20 项业务检查通过，四次服务停止及端口关闭均通过；不能消除上述 Windows 核验失败。
- [Linux 解析器资源限制](linux-resource-tests/20261030T085300Z/pytest.xml)：实际触发地址空间、文件大小及 CPU 限制，2 项通过；CPU 子进程由系统杀死。Ubuntu 26.04.1 / Python 3.14.4，运行日志见 [transcript](linux-resource-tests/20261030T085300Z/transcript.txt)。Windows Job Object 内存上限另经单项测试触发并通过。
- 知识库浏览器截图人工核看：Chromium 桌面和 Edge 390 像素窄屏的引用文本及位置可见；这只是截图检查，不覆盖全部人工交互场景。
- [第一次浏览器检查](browser-tests/20261030T014406135163Z/report.json)：18 项通过，2 项失败，原因为新增测试中的标题定位同时匹配两个元素；定位已修正。
- [第二次浏览器检查](browser-tests/20261030T050030811519Z/report.json)：Chromium 新增用例通过；同时运行的前端安装重建依赖目录，导致其余用例失败或未运行。该记录不能作为浏览器验收通过的证据。
- Python `pip check` 未发现依赖冲突；安装本版依赖修改了本机 `agent` Conda 环境。
- [独立 wheel 检查](release-audit/20261030T085953563506Z/report.json)通过，构建用于测试，不是 Release 安装包。

已通过项目和仍未证明的范围逐项见 [验收矩阵](acceptance-matrix.md)；仍需完成清单中的剩余网页人工场景及最终提交对应的 main CI、标签 CI 和源代码 Release 核验。完整原始清单见 [发布前待验收清单](../../development/v0.8.0/ACCEPTANCE.md)。

2026-10-30 安装 WSL 2 和 Ubuntu 至 `D:\WSL\Ubuntu` 后，使用 Ubuntu 26.04.1 / Python 3.14.4 在隔离虚拟环境运行 [Linux 知识库专项测试](linux-tests/20261030T083545Z/pytest.xml)：11 项通过、2 项跳过（Windows 专项和未提供公开 PDF），包括解析超时终止和临时文件清理。运行日志见 [transcript](linux-tests/20261030T083545Z/transcript.txt)。Python 3.12 CI 和完整发布验收仍未完成。
