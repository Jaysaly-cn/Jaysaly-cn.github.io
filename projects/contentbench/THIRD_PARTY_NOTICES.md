# 来源与复用

- FastAPI（MIT）、Starlette（BSD-3-Clause）、HTTPX（BSD-3-Clause）、Uvicorn（BSD-3-Clause）、Pydantic（MIT）；锁定安装版本在 requirements-lock.txt。
- SQLite 由 Python 标准库提供；前端使用原生 DOM API，无外部 CDN。
- 安全中间件与数据库事务习惯复用本作品集 SupportOps / EvidenceBrief 的自有 MIT 源码；本应用业务模型、审核版本机制与前端另行实现。不是复刻商业营销产品。
- 本机验证采用 Qwen2.5-0.5B-Instruct GGUF（Apache-2.0）与 llama.cpp（MIT），官方地址与文件校验见 docs/LOCAL_MODEL.md。权重与运行二进制不包含在本仓库。
- 样例品牌及数据全部合成。没有将开源来源隐去，也没有将第三方项目开发经历写作自己的经历。
