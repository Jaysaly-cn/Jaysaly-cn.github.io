# SupportOps — 证据驱动的客服协作台

面向小团队客服与内部支持：将知识资料、答复证据、负面反馈和人工工单放进一个可运行的工作流。

**这是有 FastAPI 后端与 SQLite 数据库的本地应用，不是预设回答的 HTML 演示。** 默认执行真实 BM25 关键词检索，显示原文证据；大模型生成是可选功能，未配置时不冒充 AI 回答。分类与优先级目前为透明关键词规则。

## 5 分钟启动

需要 Python 3.12（当前验证版本 3.12.7）。在本仓库目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

macOS / Linux 将 `.\.venv\Scripts\python.exe` 替换为 `.venv/bin/python`。

打开 http://127.0.0.1:8765 ，点击「载入 8 篇合成示例资料」，试问「首次购买订阅的退款条件是什么？」。

完整体验：载入资料 → 检索问题 → 核对来源 → 记录反馈 → 转工单 → 填处理人并改为处理中 → 填解决记录并标记已解决 → 刷新页面确认记录保留。

## 已实现

- TXT / Markdown 文件读取、粘贴导入、资料删除、对客/内部检索范围筛选。
- 中英文 BM25Plus 检索、分块、出处/版本/原文快照、无命中提示。
- 可选兼容 Chat Completions 的模型接口；JSON 与引用编号校验、超时、失败显式降级；生成结果不会自动发给客户。
- 回答历史、JSON 证据导出、正负反馈、Badcase 队列、实际使用计数。
- 工单创建去重、处理人、状态流转、解决记录、乐观并发控制、审计事件。
- 远程访问令牌、同源请求检查、写入频率限制、响应 CSP；密钥只在服务端环境变量。

## 免费模型（可选）

2026-09-23 已真实测试免费本机 Qwen2.5 0.5B / 1.5B（llama.cpp CPU）。小模型存在协议失败、无依据赔偿和虚假操作完成声明，因此 **默认客服服务仍使用证据检索，未将小模型判定为可用的自动答复方案**。原始输出、淘汰理由见 [模型评测](docs/MODEL_EVALUATION.md)。没有使用付费 API。

有免费账号时可在启动服务前设置：

```powershell
$env:LLM_BASE_URL='https://openrouter.ai/api/v1'
$env:LLM_MODEL='填写当前可用的 :free 型号'
$env:LLM_API_KEY='在本机填写，不提交仓库'
```

本地模型只需设置 URL 和模型名，不要求 Key。实际评测使用 `http://127.0.0.1:8771/v1` + `portfolio-qwen-1.5b`，运行 `python -m evals.live_model`。模型部署及哈希见 [本机模型](docs/LOCAL_MODEL.md)。远程只允许确切的 OpenRouter 端点、`:free` 型号和 Key；其他远程型号在发请求前拒绝。

- 免费模型说明：https://openrouter.ai/blog/tutorials/how-to-get-the-lowest-cost-llm-inference-on-openrouter/
- Windows 本地模型：https://ollama.com/blog/windows-preview

## 验证与评测

```powershell
python -m pytest -q
python -m evals.run
```

若 Windows 默认临时目录不可访问，为 pytest 指定一个**新建且位于工作目录内**的 `--basetemp` 目录。

`artifacts/evaluation.json` 是 20 条合成检索开发集报告。16 项接口/协议测试中的模型响应使用 mock；`artifacts/live-model*.json` 则来自真实本机模型，记录六个开发问题及失败输出。两类结果分开，不把协议通过率当模型准确率。

## 部署

GitHub Pages 不支持此应用的 Python 后端。可用 Docker 在已有服务器运行：

```sh
docker build -t supportops .
docker run --rm -p 127.0.0.1:8765:8765 -v supportops-data:/app/data \
  -e SUPPORTOPS_ACCESS_TOKEN="replace-with-your-random-token" supportops
```

需在入口配置 HTTPS 反向代理、240KB 请求体限制、持久化磁盘与备份。使用单 worker；令牌是团队共享访问控制，**不是多租户、角色权限或客户隔离**。不要向公网匿名开放真实内部资料。已另设下文所述临时访客演示，尚无稳定云部署。

当前提供的是小规模单团队版本：最多 100 篇、每篇 50000 字符；按请求重建检索索引；不支持 PDF/OCR/向量检索；文档“内部”仅用于检索范围筛选，授权用户仍能管理所有资料；文档删除后历史快照仍保留，尚无合规删除与数据保留策略。模型结构校验不能证明所有事实都由引用支持。

## 产品设计与归属

见 [产品说明](docs/PRODUCT.md)、[第三方来源](THIRD_PARTY_NOTICES.md) 与 [进展](STATUS.md)。产品方向由作品集作者定义，代码与测试通过 AI 编程协作完成；不声称存在真实客户落地、商业收入或业务提效数字。


## v0.2 工单解决经验回流知识库

已解决工单可将解决记录编辑为通用知识，填写适用范围与审核说明，勾选已核对事实及去除个案隐私后发布。内部问题只能生成内部知识；对客问题继承对客范围，发布前需人工判断正文是否适合该范围。此范围不是账户权限隔离。

POST `/api/tickets/{id}/knowledge` 接收 version/title/content/review_note/reviewed；当前工单必须已解决且版本一致，每个版本只允许发布一次，遵守100篇文档上限。正文至少20字、审核说明至少5字。新知识立即进入后续检索，但不会改写旧回答。

工单详情保存发布时的工单、原回答及引用、知识正文和审核说明快照。删除知识或重开工单不抹掉该记录；重开也不会自动撤回已发布知识，应人工评估是否从知识资料中移除。尚无自动隐私检测、多人审核或客户自动发送。

19项测试通过。浏览器从合成已解决工单编辑发布，再次提问时新知识位于首条；旧回答保持不变。额外弱相关片段仍可能出现，不将关键词检索当成事实判断。证据：artifacts/knowledge-loop.json。此轮未新增模型评测，新表单手机布局未单独验收。


## v0.3 知识变更复查

在“质量与反馈”对旧问题点击“用当前知识复查”。复用原问题及检索范围，使用现有BM25检索当前知识，冻结前后证据和当前文档ID/版本/正文SHA256清单；不调用模型，也不产生自动改善分数。此清单用于标识当次资料，不是完整知识库备份。

人工选择证据更有帮助、更差、无明显变化或无法判断，并填写依据、确认后保存。单次复查判断不被覆盖；可以另做复查。每个原问题最多20次，列表显示最近50次。旧回答、负面反馈和工单状态均不改写。若旧记录包含模型答复，此处仍只比较检索证据，不比较生成质量。

接口：POST `/api/runs/{id}/rechecks`；GET `/api/rechecks`；POST `/api/rechecks/{id}/review`，提交 verdict/note/reviewed。21测试通过，浏览器实测从旧反馈创建对照并保存判断；证据 artifacts/knowledge-recheck.json。由编程代理使用合成资料验收，不是客户评价或独立效果评估，新表单未单独完成手机验收。

## 临时访客演示 · 2026-09-23

[在线体验](https://entry-drill-quarterly-selected.trycloudflare.com)。每位访客独立 SQLite 空间，预置8篇合成知识。检索→反馈→工单认领与解决→人工审核知识回流→原问题复查均可操作。输入在演示服务器处理，请仅使用合成资料。演示依赖开发机与临时隧道，不是稳定托管。

明确禁用模型生成：免费小模型实测有无依据承诺，所以演示显示真实BM25原文证据。即使服务器配置了模型，演示接口也拒绝use_model=true。已有模型接入与失败评测仍保留，不将检索当作模型答复。

运行方式：设置 SO_DEMO_HOST 为确切演示域名，执行 python -m uvicorn app.demo:app --host 127.0.0.1 --port 8802。只运行单 worker；代理头仅信任实际反向代理。隔离入口复用本作品集 FeedbackLens MIT 代码，私人工作台仍使用原来的访问规则。

30分钟会话、最多12个同时会话、每小时30个新会话、每会话60次写入、单次40KB。后台每20秒清理已过期且无活跃请求的数据库；重启失效。Cookie 使用HttpOnly、SameSite=Strict，HTTPS下Secure。跨站请求和未知域名拒绝。访客隔离不等于内部/对客知识的角色权限控制；当前访客能管理自己空间全部资料。

26项测试通过，新增覆盖完整知识回流与复查隔离、过期清理、输入边界、模型禁用及私人令牌保护。公网HTTP双访客验收见 artifacts/public-demo-acceptance.json；浏览器实操和390px视口保存复查结论见 artifacts/public-browser-acceptance.json。初次问题只命中弱相关恢复窗口；新增合成知识后首位命中恢复步骤，旧记录和负面反馈保留，不据此宣称真实客户提效。
