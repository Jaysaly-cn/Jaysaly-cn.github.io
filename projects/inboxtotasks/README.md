# InboxToTasks — 邮件待办工作台（开发中）

第六款作品，目标是把邮件中的承诺、负责人、期限和原文证据连接到可跟进任务。

当前完成离线 `.eml` 导入、SQLite留存、原文引用待办、免费模型候选、确认与跟进、审计记录与冻结导出，以及本地浏览器工作台。启动后打开 http://127.0.0.1:8791 ，可从“用合成邮件开始”体验。公开案例：https://jaysaly-cn.github.io/cases/inboxtotasks.html 。案例站不是在线后端。

复现完整开发环境：Python 3.12虚拟环境中执行 `pip install -r requirements-lock.txt`，再运行测试与服务。锁文件包含测试依赖；CI在Ubuntu/Python3.12重新安装并验证。模型运行时和权重单独提供，不随Python依赖安装。

```powershell
python -m app.cli import samples/request.eml
python -m app.cli list
python -m app.cli show <返回的邮件ID>
```

CLI使用Python 3.12标准库。后端安装 `pip install -r requirements.txt` 后运行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8791`。开发测试使用 `python -m pytest -q`，目前27项通过。前端语法检查 `node --check web/app.js`。

模型配置：`IT_MODEL_BASE_URL=http://127.0.0.1:8771/v1`、`IT_MODEL=portfolio-qwen-1.5b`（需要先启动对应本地服务）。POST `/api/messages/{id}/suggest` 提取候选，GET `/api/messages/{id}/model-runs` 查看原始输出与失败记录。仅允许本机或明确的OpenRouter `:free`型号（需IT_MODEL_API_KEY）；不会自动注册服务或购买额度。

每封最多30次模型尝试，正文最多4000字符，超长明确拒绝而非截断。逐字引用、姓名和期限短语做位置校验，不代表语义正确。提议责任人和期限与已确认值分开。四条真实合成开发样例中，明确任务被提取、否定和旧引用返回空；**改期任务被漏提**。完整原始结果在artifacts/live-model.json，不是盲测准确率。

API流程：POST `/api/messages`（原始EML字节）→ GET `/api/messages/{id}` → POST `/api/messages/{id}/tasks`（title、quote、可选quote_start）→ POST `/api/tasks/{id}/confirm`（version、owner、due_date或null、note、conflict_ids）→ POST `/api/tasks/{id}/state`（version、state、note）。修订 `/revise` 会恢复draft并清空已确认责任与日期。GET `/history` 保留每次快照。POST `/api/exports` 冻结已确认任务与邮件依据，GET `/api/exports/{id}` 下载JSON。

候选不可跳过确认直接完成；确认会记录已核对的Message-ID冲突。完成/取消任务允许说明原因后重新打开。日期由人明确指定，不自动解释“周五”；无期限使用null并在确认说明中解释。访问令牌环境变量为 `INBOXTOTASKS_ACCESS_TOKEN`；未配置时仅允许本机访问。尚无多用户权限系统。

原始字节与 SHA-256、规范化正文与正文哈希分别留存。优先纯文本，HTML 仅转换为文本且标注局限，不访问图片、链接或附件；附件原样包含在原始邮件中。相同原始字节幂等，同 Message-ID 不同内容保留两份并提示冲突。邮件日期头仅记录，不据此自动推算期限；被引用的旧邮件文字也仍在正文中，下一阶段需人工区分责任与时间。

边界：单机500封、每封2MB、正文10万字符；不会静默截断。没有邮箱OAuth、后台同步、自动回复或发送功能。数据库包含导入的原邮件，请只用合成资料演示。CLI 是工程阶段产物，任务工作流与模型验证完成前不宣称 AI 能力可用。
