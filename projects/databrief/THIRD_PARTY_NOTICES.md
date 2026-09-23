# 研究与来源 · 2026-09-23

- PandasAI官方仓库 https://github.com/sinaptik-ai/pandas-ai ：对话式数据分析参考。官方README说明社区代码MIT，ee有独立条款。当前仅调研，没有复制该仓库源码、UI或品牌。
- SQLite授权回调 https://www.sqlite.org/c3ref/set_authorizer.html 与进度回调 https://www.sqlite.org/c3ref/progress_handler.html ：通过Python标准库sqlite3调用。
- 本作品集已有MIT项目的SQLite连接模式被复用。DataBrief解析与查询实现为本项目代码。
- Python标准库csv/sqlite3负责解析和执行；未新增模型权重或第三方分析引擎。
- app/model.py复用InboxToTasks MIT适配器结构，改为DBR_MODEL系列变量与schema-only SQL提议。app/security.py复用同作品集MIT单机访问保护。已接入现有本机Qwen2.5-1.5B-Instruct Q4_K_M/llama.cpp b11118服务，不下载新权重，来源校验记录沿用local-model-runtime，模型许可证不由本仓库MIT替代。

- app/demo.py 改编自本作品集 EvidenceBrief 的 MIT 临时演示实现，复用会话隔离、限额和清理机制，改为 DataBrief 数据集种子与模型提议路由。
