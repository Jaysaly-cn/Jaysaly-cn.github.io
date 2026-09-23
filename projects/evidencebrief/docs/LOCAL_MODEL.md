# 免费本机模型运行记录

2026-09-23 下载 Qwen2.5-0.5B-Instruct Q4_K_M，使用 llama.cpp b11118 Windows x64 CPU，4 个线程、8192 上下文、单并发。本机内存约 32GB。仅绑定 `127.0.0.1:8770`，无付费 API、无需 Key。二进制和模型只留本机，不提交到项目源码。

- 运行包：https://github.com/ggml-org/llama.cpp/releases/download/b11118/llama-b11118-bin-win-cpu-x64.zip
- 运行包 SHA256：`7f8431c69471cf8991f43da4af6e80f3a66778a63055004a9211ebba00d68084`（已与 GitHub release asset digest 对照）
- 模型：https://modelscope.cn/models/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/2e50b77b0eee3083842019e257b74854323d880a/qwen2.5-0.5b-instruct-q4_k_m.gguf
- 模型大小：491400032 字节
- 模型 SHA256：`74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db`（实际下载已校验，与 ModelScope API 和 Hugging Face 官方模型文件页一致）
- 官方文件页：https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/blob/main/qwen2.5-0.5b-instruct-q4_k_m.gguf

Hugging Face 本机直连超时，改从 Qwen ModelScope 同名仓库下载相同哈希文件。模型属于 Apache-2.0，llama.cpp 属于 MIT；源代码项目保留来源指引，不打包权重。

在本目录运行：

```powershell
./llama/llama-server.exe -m qwen.gguf --host 127.0.0.1 --port 8770 --ctx-size 8192 --threads 4 --parallel 1 --alias portfolio-qwen
```

端点 `http://127.0.0.1:8770/v1`；模型名 `portfolio-qwen`。小模型输出质量有限，需要逐句审核；生成测试产物在 ContentBench 的 artifacts 中。

## 1.5B 对照模型

同日增加 Qwen2.5-1.5B-Instruct Q4_K_M，对照客服与证据抽取中发现的 0.5B 错误。

- 官方来源：https://modelscope.cn/models/Qwen/Qwen2.5-1.5B-Instruct-GGUF
- 固定文件：https://modelscope.cn/models/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/e8b19c78f775ccbcf6df15ceace6bb5276f09765/qwen2.5-1.5b-instruct-q4_k_m.gguf
- 字节数：1117320736；SHA256：`6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e`，已核对 ModelScope 仓库 API 与实际下载文件。
- 本机文件：`qwen-1.5b.gguf`。完整下载并通过校验后才运行。

```powershell
./llama/llama-server.exe -m qwen-1.5b.gguf --host 127.0.0.1 --port 8771 --ctx-size 8192 --threads 4 --parallel 1 --alias portfolio-qwen-1.5b
```

此处端点为 `http://127.0.0.1:8771/v1`，模型别名 `portfolio-qwen-1.5b`。性能与效果见各应用的真实评测记录，不预先假定更大模型必然正确。
