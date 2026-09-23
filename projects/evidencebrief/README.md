# EvidenceBrief — 竞品研究与证据工作台

从一个明确的研究问题开始：建立比较对象和维度，采集公开网页或粘贴原文，将结论关联到原文，再经人工确认生成对比矩阵、缺口清单和可追溯报告。

这是独立的 **FastAPI + SQLite** 应用。网页采集、来源去重、引用校验、审核与报告快照均执行真实后端逻辑；不是预设的 HTML 结果。未配置模型时是可用的结构化研究工具，**不是自动深度研究 Agent**。

## 本地启动

需要 Python 3.12。在本仓库目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8766
```

打开 http://127.0.0.1:8766 。Linux/macOS 将 Python 路径替换为 `.venv/bin/python`。

1. 新建项目，例如比较 Alpha、Beta，维度为价格、导入格式。
2. 选择“粘贴原文”保存材料，或“采集网页”输入公开 HTTPS 地址。
3. 阅读已保存来源，复制其中连续原文，填写对应维度与候选结论。
4. 在“结论审核”核对上下文、时间和适用条件，填写审核说明并确认。
5. 在“对比与缺口”查看已确认事实、不同表述与尚缺证据的单元格。
6. 生成报告版本，下载 Markdown 与 JSON。归档来源后新报告排除其结论，旧报告不会被改写。

资料默认存储于 `data/evidencebrief.sqlite3`，重启保留。不同研究项目之间不能交叉绑定来源、结论或报告。

## 可验证能力

- **真实来源采集**：只接收公开 HTTPS，逐跳验证 DNS 地址并将连接固定到已验证 IP，TLS 仍检查原始主机名；不携带登录 Cookie，不绕过访问限制。最多 3 次重定向，正文上限 1MB；HTML / text/plain 支持，PDF、需登录或前端渲染内容不支持。
- **来源快照**：保存采集时间、用户提供的发布日期（网页不会猜发布日期）、原文、正文 SHA-256；HTTPS 另存接收字节哈希。粘贴网址仅作来源注记，不表示系统已访问验证。
- **证据关联**：引用必须是来源中的连续原文，记录字符起点；保存实体/维度。原文存在不等于结论语义正确，因此仍需人工审核。
- **研究对比**：只纳入已确认、未归档的证据；缺口不是“不支持”；同一对象/维度出现不同表述只是复核线索，不冒充语义冲突检测。
- **可复现报告**：生成时冻结矩阵与来源；之后修改审核状态、归档资料不会改写历史版本。
- **模型候选（可选）**：仅免费 OpenRouter `:free` 型号或本地模型；提取候选必须通过结构与逐字引用校验，所有候选仍是 draft；一次建议中任一引用无效则整批回滚。

## 免费 / 本地模型

已接入免费本机 Qwen2.5-1.5B-Instruct Q4_K_M，通过 llama.cpp CPU 运行，无 API Key。五条合成开发问题真实调用均返回可校验候选，但仍有否定信息和套餐限制漏提，不能称为 100% 准确率。0.5B / 1.5B 原始失败与提示迭代见 [模型评测](docs/MODEL_EVALUATION.md)。默认不自动调用，需点击提取按钮。

本机启动前设置 `EB_MODEL_BASE_URL=http://127.0.0.1:8771/v1`、`EB_MODEL=portfolio-qwen-1.5b`。部署与哈希见 [本机模型说明](docs/LOCAL_MODEL.md)。v0.2 按最多3600字符、重叠240字符分段，支持逐段查看、批量继续、失败重试和停止。分段状态持久化；覆盖按成功范围的并集计算，报告冻结当时的处理范围。候选不会自动批准，不保证完整召回。

启动前设置环境变量（`.env.example` 仅示例，不自动加载）：

```powershell
$env:EB_MODEL_BASE_URL='https://openrouter.ai/api/v1'
$env:EB_MODEL='填写当前可用的 :free 型号'
$env:EB_MODEL_API_KEY='仅在本机填写'
```

本地兼容服务可使用 `http://127.0.0.1:11434/v1`，模型名必须已安装。点击提取时将来源前 20000 字符发送给指定模型。不自动下载权重、注册账号或切换到付费型号。JSON 模式需供应商支持。

## 测试与部署

```sh
python -m pytest -q
python -m evals.run
node --check web/app.js
```

36 项自动测试覆盖研究流程、跨项目边界、原文校验、归档行为、历史报告冻结、审核版本冲突、模型整批回滚、URL 过滤和重定向。协议测试使用 mock；另运行 `python -m evals.live_model` 可重复真实本机模型开发评测。11 项合成工作流评测只验证应用不变量。

Dockerfile 为单服务部署入口。需要持久化 `/app/data`，远程必须设置 `EVIDENCEBRIEF_ACCESS_TOKEN`；不要信任所有来源的转发头，保持单 worker。公开部署应由 HTTPS 代理接入、限制请求体并建立磁盘备份。当前尚未提供公网动态服务。

此版本采用团队共享令牌，不是用户/租户隔离。每项目最多 8 个对象、12 个维度、30 份来源、200 条结论和 50 个报告。网页解析为标准库文本抽取，可能含导航文本，不等同浏览器渲染或成熟正文算法；页面出现错误字符时应改用人工粘贴。DNS 查询由系统 resolver 控制超时，连接/读取各有限时，不保证整次调用严格在 25 秒内完成。

## 产品与来源

[产品设计](docs/PRODUCT.md) · [第三方来源](THIRD_PARTY_NOTICES.md) · [开发状态](STATUS.md)

产品方向由作品集作者定义，代码与测试使用 AI 编程协作完成。尚无真实客户验证与业务提效数字。


## v0.3 人工修订与版本记录

审核卡片可展开原文前后180字符并高亮引用，直接修改结论、维度、引用及必要的全文位置。修订说明必填；任何内容修订都会恢复为待审核并清空旧审核说明，不能沿用旧批准。旧报告保持原快照。

SQLite保存每次修订和审核状态的完整版本。旧记录在第一次变更时保存当时基线，不补造历史；当前共享令牌工作台不提供审核人员身份归属。重复引用须扩展上下文或填写正确的全文位置，不允许跨项目或已归档来源修订。

本轮36项测试通过；浏览器将此前真实模型遗漏团队版限定的候选补齐、重新审核，版本1/2/3可查看。`artifacts/browser-revisions.json` 记录合成验收；模型本身未改变，不将人工修订算成模型准确率提升。


## 持久化研究执行计划（本机 API / CLI）

为选定来源建立跨资料分段计划，按次调用既有抽取工具，每步保留来源哈希、分段范围、尝试数、状态和候选ID。此功能目前提供 API 与 CLI，网页调度面板尚未接入，临时公网演示不开放批处理。

```powershell
python -m app.agent_cli plan <项目ID> --source <来源ID1> --source <来源ID2>
python -m app.agent_cli run <项目ID> --batch <返回的计划ID> --steps 2
python -m app.agent_cli status <项目ID> --batch <计划ID>
python -m app.agent_cli run <项目ID> --batch <计划ID> --steps 1 --retry-failed
python -m app.agent_cli pause <项目ID> --batch <计划ID>
python -m app.agent_cli resume <项目ID> --batch <计划ID>
```

默认本机8766；远程地址可用 --base-url，认证读取 EVIDENCEBRIEF_ACCESS_TOKEN。每次run默认最多1步，可显式指定1至32步；遇到新失败停止，不无限重试。有失败步骤时run退出码2，网络异常退出且提示先查状态。暂停不强制中断当前步骤，关闭CLI后当前请求也可能完成，应先查status。

每项目最多10计划，每计划最多8个来源和32个分段，超限拒绝而非截断。先执行待处理/中断步骤；只有显式 --retry-failed 才在待处理步骤耗尽后重试失败。已成功分段复用；重启后持久化running记录显示interrupted，下次执行依据分段缓存恢复。单进程执行，不能部署多个worker。计划完成只指抽取步骤完成，不代表事实完整或研究质量达标；不会自动抓网页、批准候选或生成最终报告。

API：POST `/api/projects/{pid}/batches` (source_ids)，GET同路径加 `/{bid}`，POST `/{bid}/next` (retry_failed)，POST `/{bid}/pause` (paused)。46项测试通过。真实Qwen两资料验收：Alpha两次校验失败，Beta一次成功且仍为draft；已成功步骤不重复调用。见 artifacts/batch-agent-live.json，不是盲测。
