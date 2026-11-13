# V1.5 本地模型文件准备记录

日期：2026-11-09。按用户要求下载候选模型和本地推理服务安装程序；本记录不表示模型已安装、导入、运行或通过评估。

- 模型：Ollama 官方仓库 `qwen3:4b-instruct-2507-q4_K_M` 的模型层，保存于 `data/v1.5-model-preparation/qwen3-4b-instruct-2507-q4_k_m.gguf`，2,497,280,480 字节。SHA-256 `85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9`，与下载的官方清单一致。
- 同目录保存官方 `manifest.json`、`config.json`、`template.txt`、`parameters.json` 和 `LICENSE.txt`；后四项的 SHA-256 与清单一致。
- Ollama 官方 Windows 安装文件 `data/v1.5-model-preparation/OllamaSetup.exe`，1,689,667,936 字节；SHA-256 `106ef3d2a02437810fba6f574914b1413c512ea84ddd4f184c8e7f434b6f5564`；Windows Authenticode 验证为 `Valid`，签名主体为 Ollama Inc.。
- 上述模型文件是从官方仓库保存的 GGUF 模型层和元信息，**不是**已经通过 `ollama pull` 注册到 Ollama 的模型。尚未安装 Ollama 或修改系统配置；后续需要安装服务并明确导入或注册模型后，才能供应用调用。
- 文件保存在 Git 忽略的项目 `data/` 目录；模型、安装器和本地会话不应提交到源码仓库。机型可用性、推理质量、GPU 占用与速度尚未实测。
