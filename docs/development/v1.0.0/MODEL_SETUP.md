# 本机嵌入模型与语义检索准备

2026-11-02，按用户“准备模型使语义检索达到可用状态”的要求完成。模型、缓存和新增推理依赖均在 D 盘；实际跑通离线嵌入、隔离文档上传、索引和语义检索预览。此记录不替代完整版本验收或代表性科研语料效果评估。

## 已安装与配置

| 项目 | 实际配置 |
| --- | --- |
| 模型 | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| 来源与许可 | [官方固定提交](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/tree/e8f8c211226b894fcb81acc59f3b34ba3efd5f42)，Apache-2.0 |
| 模型目录 | `D:\astroagent-models\minilm-v1` |
| 模型文件大小 | 499,557,407 bytes，约 476 MiB；不含重复缓存 |
| 固定提交 | `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` |
| 模型目录 SHA-256 | `1daaecb5ccf506a52cd67ffa88319d56efff7112b6f02b6f3d06a51e92f45d39` |
| 向量 | 384 维、归一化；CPU 推理 |
| Python 入口 | `D:\astroagent-runtime\venv\Scripts\python.exe` |
| 新增依赖 | PyTorch `2.15.0+cpu`、Sentence Transformers `5.7.0`、Transformers `5.22.1`、Hugging Face Hub `1.33.0`、Safetensors `0.8.0` |
| 缓存与临时目录 | `D:\astroagent-runtime\cache`、`D:\astroagent-runtime\temp` |

专用 venv 复用已安装的 `E:\miniconda3\envs\agent` Python 3.12.13 及既有项目基础依赖；本次新增推理包安装在 D 盘 venv 中。不是把新依赖安装回旧环境。该运行环境仍依赖原来的 Python 基础环境。

项目私有 `.env` 已填写 `ASTROAGENT_RAG_MODEL_PATH`、`ASTROAGENT_RAG_MODEL_SHA256`、模型名称、384 维和语义检索启用项；保留原数据库连接，不复制凭据到本文。配置备份及机器安装清单位于被 Git 忽略且受限 ACL 保护的 `.astroagent/model-setup`。

模型下载使用固定提交和文件扩展名白名单，运行时使用 safetensors、关闭远程仓库代码，嵌入子进程禁止网络连接，并保留原来的 120 秒 / 3 GiB 保护。启动入口将缓存目录传给嵌入子进程，避免新增缓存落在 C 盘。

## 启动和使用

当前本机前后端已启动，访问 [工作台](http://127.0.0.1:5173)；设置页面可看到数据库与嵌入模型已配置。之后重新启动后端请使用专用环境入口：

```powershell
powershell -File scripts/start_backend.ps1
```

前端仍使用现有开发入口：

```powershell
cd frontend
npm run dev
```

在工作台创建或打开项目，进入本地知识库上传自己的 PDF / Markdown，再进入“文献知识问答”，点击“确认构建新索引代”。索引 ready 后输入问题，点击“检索并预览”。预览中的语义状态应为 `ready`；关键词无匹配时仍可返回语义相关片段。

本次没有向日常数据库加入演示文档或索引。每个项目仍需针对实际导入的文献显式构建索引。模型配置和本地检索不需要回答服务密钥；向回答服务发送证据并生成回答仍需单独配置及用户确认。

## 本次可用性核验

完整记录见 [model-readiness.json](model-readiness.json)。使用真实模型和应用 API，在临时数据库以日常应用账号建立表、上传两份明确标为合成核验材料的英文 Markdown、构建 2 段索引，然后执行中文和英文问题。没有替换嵌入器，没有调用回答或科研服务，临时数据库已经删除。

| 核验项 | 实际结果 |
| --- | --- |
| 离线嵌入 | 2 × 384，向量归一化通过，首次 85.437 秒 |
| 文档与向量索引 | ready，2 段，42.438 秒 |
| 中文问题检索英文片段 | `semantic_status=ready`，词法候选 0，语义候选 2，含预期星团材料；39.047 秒 |
| 英文问题检索英文片段 | `semantic_status=ready`，词法候选 0，语义候选 2，含预期星团材料；39.062 秒 |
| 本机服务 | 后端 `/api/v1/setup/status` 显示 ready / embedding_configured；前端和 API 代理均返回 200 |

这些结果证明本机链路可运行，不证明普遍检索准确率、首位排序质量或科研结论可靠。两份合成材料不是独立标注的代表性文献集。本次未执行完整回归、发布构建、CI 或发布。

固定模型的 `max_seq_length` 为 128 token，较长片段会按模型配置截断；当前原文分段上限为 1200 字符，两者不等价。真实长文、PDF 版式、中英文术语覆盖、性能与科学支持关系仍需发布前验收。当前 CPU 单次查询约 39 秒，不能把该结果解读为即时检索或所有设备的性能承诺。
