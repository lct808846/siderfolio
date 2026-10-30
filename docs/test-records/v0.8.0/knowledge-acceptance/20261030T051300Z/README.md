# 公开 PDF 与边界检查

2026-10-30，Windows，临时测试数据库。运行 `tests/test_knowledge.py` 中 `public_pdf or oversized_upload or tampered`，结果见 [JUnit](pytest.xml) 和 [输出](transcript.txt)。公开文件不复制进仓库。

公开 PDF：Priyatikanto 等，《The dynamical fate of binary star clusters in the Galactic tidal field》，[arXiv:1601.01752](https://arxiv.org/pdf/1601.01752)，14 页，1,518,346 字节，SHA-256 `1d6061aa93ebf27b55dba44c41311d7dfad95f4f8f73161c1802b51f5cb714a2`。检查实际字节下载一致、首页文本包含标题、检索“dynamical fate”的引用包含物理页 1。该首页检查不覆盖完整页面人工核对或扫描件。

另渲染并人工查看物理页 3：该页双栏且含公式，提取的章节编号 2.1、2.2、2.3 出现顺序与页面阅读顺序一致，并包含公式编号 (1)、(2)。首次简单搜索将正文里提前出现的术语误当成标题，之后改为匹配章节编号；未据此声称公式内容或所有版式均提取正确。纯图像 PDF 另用合成文件验证无 OCR。

首次以较宽关键词“binary star clusters”要求前五结果必须包含首页，断言失败；前五排名本身不保证首页，改为标题关键词后重测。该初次直接执行没有归档输出。

上传超 20 MiB 被拒且项目未新增文档或修订；完整备份的原文被篡改且外层清单哈希被重新计算后，导入仍拒绝且项目数量不变。其余限制、归档异常和平台资源限制仍需验收。
