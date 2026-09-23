# EvalDesk · AI 评测工作台

面向提示词迭代：固定测试集，比较候选提示词，保存失败输出，再由人复核业务含义。现有版本化测试集编辑器、网页任务执行与自动导入、SQLite 人工复核与中文对比网页。临时访客隔离演示已验证；作品集发布入口为[独立案例](https://jaysaly-cn.github.io/cases/evaldesk.html)与[源码镜像](https://github.com/Jaysaly-cn/Jaysaly-cn.github.io/tree/main/projects/evaldesk)。

临时体验：[EvalDesk 公开演示](https://perform-determined-shipped-rca.trycloudflare.com/)。入口依赖开发机与隧道在线，可能失效，尚非稳定云托管。

## 已实现

- 受限 JSON 测试集：2–3 套提示词、最多 20 个样例、每例最多 8 个断言。
- 复用 Promptfoo 0.123.1 执行，固定本地 Qwen 1.5B 模型；无付费 API。
- 确定性断言支持 equals、contains、not-contains、is-json，以及固定反馈/变更结构 v1 规则，不接受用户脚本、自定义 provider 或模型裁判。
- 每次运行独立目录，保存测试集、生成配置、原始结果、日志和 SHA-256；不覆盖旧运行。
- 人工判据保存在每个样例中，首次导入全部待复核；人工判断与自动断言分别统计，自动通过不代表语义正确。
- 按上游 `failureReason` 区分断言失败与调用错误；拒绝重复、缺失或身份不匹配的结果单元。
- SQLite 追加人工复核与修订历史，过期版本返回 409；调用错误不能判为业务正确。
- 桌面并排 / 手机纵向对比，失败与待复核筛选，未保存草稿保护，冻结 JSON 报告下载。
- 网页编辑提示词、样例、业务判据和自动检查；从历史运行复制，保存版本说明和快照；过期修改拒绝、旧版只读回看和下载。不自动执行模型。
- 在任务页显式启动某个保存版本，由独立工作进程执行并自动导入结果。请求标识幂等、单数据库最多一个活动任务；失败重试创建新记录，旧任务保留。
- 记录工作进程与引擎进程的 PID 和创建时间，重新打开页面或重启网页服务后核实存活状态。无法核实则保留待核查，不自动重复调用。
- 查看任务诊断、末尾日志与恢复历史。进程确认结束且完整证据匹配原任务时，可恢复导入已有结果，不重新运行模型；恢复事务保留原失败原因。

## 运行

需要 Node.js >=22.22、Python 3.12，以及在 `http://127.0.0.1:8771/v1` 提供 `portfolio-qwen-1.5b` 的本地兼容服务。可用环境变量 `ED_NODE_BIN` 指定 Node 可执行文件；安装依赖和运行应使用同一个 Node 版本，以匹配原生依赖。

```powershell
python -m pip install -r requirements.txt
$env:PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = '1'
npm ci --no-audit --no-fund
python engine.py samples/ticket-routing.json
# 将上一步打印的运行目录导入；也可直接导入仓库自带的真实合成评测：
python store.py artifacts/engine-spike
python -m uvicorn app:app --host 127.0.0.1 --port 8803
```

打开 http://127.0.0.1:8803 。导入同一证据幂等；同一个运行 ID 出现不同内容会拒绝。导入会检查文件哈希和受限编译配置，并将证据保存到 SQLite，随后不依赖原目录。原始快照初始语义状态仍为 pending；网页人工复核保存在独立记录中。`EVALDESK_DB` 可指定网页数据库路径，对应导入时使用 `--db`。

测试集编辑器位于 `/suites.html`。保存后进入 `/jobs.html`，选择版本并点击“运行本地评测”。任务完成后点击结果链接即可复核。启动服务前配置好 `ED_NODE_BIN`，工作进程会继承它。也可下载 JSON 后使用原 CLI；旧版不被覆盖，每个测试集上限 100 个版本。

任务记录持久化到同一个 SQLite；日志在数据库旁的 `job-logs/<任务ID>.log`，原始评测在 `job-runs/<任务ID>/`。关闭网页不会取消评测。单机任务不自动排队，已有活动任务时新请求返回 409；终态失败/中断可以显式新建重试。若模型已运行完成但导入中断，优先在“查看诊断”中恢复已有结果。恢复时重新校验进程状态、证据哈希、任务 ID 和测试集版本；事务内同时导入与记恢复历史，重复恢复幂等。日志最多展示各 16KB 尾部。

状态待核查时阻止新任务。缺失引擎进程身份或无法读取进程状态时仍需管理员核查，网页不能强制清除该状态。未实现取消、多机调度或账户隔离。

```powershell
New-Item -ItemType Directory -Force data | Out-Null
python -m pytest -q --basetemp=data/pytest-temp
```

安装 Python 依赖：`python -m pip install -r requirements.txt`。执行层本身仅使用标准库，网页使用 FastAPI。首次安装依赖需要联网。执行时关闭 Promptfoo 遥测、版本检查、结果分享及其默认数据库写入。`data/` 不提交到仓库；可公开的合成评测另存为 artifacts。

## 验证范围

已完成 41 项测试及多轮真实本地模型调用。首轮两套提示词各 2/4 精确标签断言通过，0 个调用错误。逐例输出与限制见 [首轮验收](artifacts/engine-spike-review.md)。原始证据按字节保存，Git 不对该目录转换换行。

恢复验收见 [隔离故障模拟](artifacts/recovery-acceptance.json)：复制数据库后模拟导入中断，浏览器恢复十个真实结果，保留模拟错误历史。原数据库未改动，没有新建评测任务；测试同时禁止恢复路径调用引擎。该故障是主动模拟，不宣称自然发生过。手机诊断布局 390px / scrollWidth 375。

独立项目工作流为 `.github/workflows/verify.yml`；源码镜像由个人主页仓库根目录 `.github/workflows/evaldesk.yml` 在 Windows / Linux 检查 Python 测试及 JS 语法。以[远程运行记录](https://github.com/Jaysaly-cn/Jaysaly-cn.github.io/actions/workflows/evaldesk.yml)为实际 CI 状态，不将配置存在写成通过。CI 复用真实输出作为固定数据，不在云 runner 调用本地模型，也不替代真实模型验收。

网页任务实际执行 v2 的 10 次调用并自动导入；另一个 v1 任务在网页服务被停止前确认工作进程存活，新服务启动后仍完成，复用原请求标识没有新增任务。记录见 [网页任务验收](artifacts/web-jobs-acceptance.json) 和 [真实重启探针](artifacts/job-restart-probe.json)。两轮原始数据在 `artifacts/job-run-2` 与 `artifacts/job-run-1`。手机页面 390px / scrollWidth 375；失败重试通过自动测试，未通过浏览器人为制造模型故障。

测试集编辑器已实际保存 v1/v2 并回看旧版，下载 v2 后完成新增 10 次本地调用，baseline 3/5、candidate 2/5、0 调用错误；新的提示词未表现出整体改进。见 [测试集验收与逐例结果](artifacts/suite-editor-acceptance.md)。该轮十个单元的持久人工复核均为 pending，不能与上一轮四样例通过率直接比较。

网页验收见 [浏览器记录](artifacts/review-browser-acceptance.json)：人工判断、另一卡片草稿保留、冻结报告、判断修订、筛选、显式丢弃草稿、390px 手机提交均实际操作。HTTP 核对冻结报告保留旧版判断，当前记录为新版本；[冻结报告](artifacts/review-report-first.json) 留有 6 项待复核，不自动补齐。截图：[桌面](artifacts/review-desktop.png)、[手机](artifacts/review-mobile.png)。

四个合成工单样例不是独立测试集，也不用于推断真实用户准确率。精确标签断言会同时惩罚多余解释和错误分类，因此需结合原始输出复核。固定 temperature=0 也不保证跨硬件完全复现。

哈希用于发现快照变化，不是签名或防篡改保证。导入目录来自可信本机用户，不接受任意网络上传。默认 app.py 工作台仅供本机使用，绑定回环地址并限制 Host / 写入来源；复核者姓名自报，未实现身份认证、账号隔离、取消或公开托管。不要把当前服务直接绑定到公网。

## 临时公开演示

公网使用独立 `demo.py` 包装，不直接暴露上述私人工作台。演示模式复用 FeedbackLens 的隔离模式，并为后台任务增加进程存活检查和独立目录。

- 每位访客独立 SQLite、结果与日志目录；种子结果是同一份真实合成评测，之后的判断和报告彼此隔离。
- 30 分钟后会话失效，重启也失效。过期且无活跃请求、无运行/待核查任务才清理；重启遗留目录在最后目录活动超过 35 分钟且任务安全结束后清理。无法确认状态时保留，交由管理员处理。
- 最多 12 个保留空间，每小时最多 30 个新会话；每会话 60 次写入、40KB 单次请求、2 个评测任务、每任务 12 次模型调用。整个演示进程每小时最多 8 个任务，跨访客一次只允许一个活动任务，不自动排队。进程重启会重置内存频率计数，但遗留活动任务仍参与全局占用检查。
- Host / Origin 校验、HttpOnly / SameSite cookie、HTTPS Secure cookie、禁止索引、接口文档关闭。只提交合成资料，输入在演示服务器处理。无账户认证和生产 SLA。

```powershell
# 已配置兼容 Node 的 ED_NODE_BIN；域名填本次隧道的实际主机名
$env:ED_DEMO_HOST = 'perform-determined-shipped-rca.trycloudflare.com'
python -m uvicorn demo:app --host 127.0.0.1 --port 8804 --workers 1
```

必须单个网页工作进程运行，状态和频率限制保存在内存。后台评测是独立子进程。私人数据库路径不会进入演示请求。

公网 [HTTP 双访客验收](artifacts/public-demo-acceptance.json) 完成真实模型任务、复核、报告、跨访客 404 和跨站 403；[浏览器验收](artifacts/public-browser-acceptance.json) 完成另一轮真实任务与报告，手机导航已实际点击验证。两轮输出保存在 `artifacts/public-http-run` / `artifacts/public-browser-run`。TTL 和活动任务清理通过测试验证，未声称在浏览器等满 30 分钟。

## 跨项目回归示例库

测试集工作室可选择 FeedbackLens / ChangeLens 各六个已知失败样例，保存后按版本执行。24次真实模型调用及逐例复核见[新基线与边界](artifacts/portfolio-regression-review.md)。JSON检查和业务判断分别统计；本轮运行参数与原工具不同，不直接比较历史通过率。来源哈希见[samples/portfolio-provenance.json](samples/portfolio-provenance.json)。

## 固定结构检查

网页可选择“反馈对象结构 v1”或“变更说明结构 v1”，检查字段、类型、长度和额外字段；不接受任意Schema。旧规则不变，v1定义冻结，后续变化需新增规则名。详见[离线重放、边界构造与真实网页任务](artifacts/schema-review.md)。结构正确不代表引用或业务含义正确，原始输出与人工复核仍保留。

## 后续交付

1. 扩展不同产品的真实失败样例，复核输出格式和业务内容之间的差异。
2. 持续迭代案例与验证记录，陈列优先级按工程深度而非项目数量。

## 开源来源

执行引擎 [Promptfoo](https://github.com/promptfoo/promptfoo)，MIT；通过锁定 npm 依赖直接复用。配置依据其[命令行文档](https://www.promptfoo.dev/docs/usage/command-line/)、[兼容模型接入文档](https://www.promptfoo.dev/docs/providers/openai/)及[遥测开关文档](https://www.promptfoo.dev/docs/configuration/telemetry/)。项目不冒充上游原创；EvalDesk 的测试集、受限执行层和后续产品流程为本仓库增量。

进程核查复用 [psutil](https://psutil.io/) 7.2.2，BSD 3-Clause，许可保存在 `third_party/psutil-LICENSE`。使用 PID 与进程创建时间共同识别任务进程，避免将复用的 PID 当作原进程。

## 演示会话可靠性更新

当前完整测试共 44 项通过。修复慢上传途中会话过期时提前清理数据库的问题，新增正常上传、超限与额度拒绝回归。[复现与范围](docs/DEMO_UPLOAD_FIX.md)。此前章节中的测试数量是对应版本的历史记录。
