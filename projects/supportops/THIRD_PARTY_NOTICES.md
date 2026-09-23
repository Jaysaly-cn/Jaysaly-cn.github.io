# 来源与复用边界

- **rank-bm25 0.2.2**：直接作为依赖调用 `BM25Plus`；上游 https://github.com/dorianbrown/rank_bm25 ，Apache-2.0。中文 bigram 预处理、业务流程与 UI 为本项目新增实现。
- **FastAPI**：HTTP 路由、请求验证与测试客户端入口，MIT；https://github.com/fastapi/fastapi
- **Uvicorn**：ASGI 服务，BSD-3-Clause；https://github.com/encode/uvicorn
- **HTTPX**：模型 HTTP 调用与接口测试，BSD-3-Clause；https://github.com/encode/httpx
- 传递依赖及其许可证由安装包一并提供。`requirements-lock.txt` 记录实际测试版本。
- Chatwoot 仅作为客服协作业务参考；未复制其代码、界面资源或 enterprise 目录。
- Dify 与 local-deep-researcher 为选型调研候选，本版本未复制代码。
- 星河协作政策、人员、工单和评测问题均为合成资料，不来自真实企业客户。

没有对上游整体改名后声称全部原创。当前项目为基于开源库实现的独立业务应用。
