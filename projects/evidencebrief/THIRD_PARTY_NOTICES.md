# 复用与来源

- FastAPI (MIT)、HTTPX (BSD-3-Clause)、Uvicorn (BSD-3-Clause)：直接使用开源库，安装包保留上游来源文件；锁文件记录实际版本。
- `app/security.py` 的访问保护模式复用本作品集 SupportOps 的 MIT 实现；研究模型、来源与报告数据模型独立。
- Python 标准库 `http.client`、`ssl`、`socket`、`html.parser`、`sqlite3` 用于采集与持久化；没有声称重新发明这些能力。
- https://github.com/langchain-ai/local-deep-researcher (MIT)：调研来源，参考来源收集→查缺补漏→带来源报告的工作流。本项目未复制上游源代码，也未实现其自主循环研究能力。
- 官方技术资料：https://docs.python.org/3/library/http.client.html
- 测试、评测中的 Alpha/Beta 定价与能力均为合成数据。

采用独立轻量研究台而非直接运行大型框架，是为了先交付不依赖模型凭据的证据审核与对比工作流。后续自动检索、重写查询和多轮研究需要另行实现并实际验证。
