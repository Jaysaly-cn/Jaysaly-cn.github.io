# DataBrief v0.2 · 运营数据分析台

第七款作品，目标为CSV→数据质量概览→自然语言分析问题→可检查的SQL→结果与图表快照。

目前完成UTF-8 CSV导入、数据概览、只读受限SQL、持久化结果、FastAPI、免费本机模型SQL提议和浏览器表格/图表工作台。启动后打开 http://127.0.0.1:8792 ，可通过“打开合成渠道数据”体验。[产品案例](https://jaysaly-cn.github.io/cases/databrief.html)提供流程与验证记录；动态工作台仍需本机启动。

后端：`pip install -r requirements-lock.txt`，运行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8792`。模型配置 `DBR_MODEL_BASE_URL=http://127.0.0.1:8771/v1` 与 `DBR_MODEL=portfolio-qwen-1.5b`，需先启动相应本地推理服务。访问令牌 `DATABRIEF_ACCESS_TOKEN`；无令牌时仅允许本机访问。

API：POST `/api/datasets?name=名称` 上传CSV字节；GET `/api/datasets/{id}` 查看概览。POST `/api/datasets/{id}/proposals` 提交question，仅保存提议，不执行。POST `/api/datasets/{id}/runs` 提交sql、可选proposal_id、reviewed=true、至少5字note，经受限执行器运行。GET同一路径读取历史；GET `/api/runs/{id}` 下载固定JSON快照。

提议原文与实际执行SQL分别保留；修改查询不改写原提议。模型只接收列映射/名称/类型/缺失计数、总行数与问题，不发送单元格样例或行值。最多30次模型提议/数据集；协议错误保留raw。仅允许本机或明确OpenRouter免费型号，未自动购买额度。

37项测试通过，`node --check web/app.js`语法通过。真实Qwen1.5B三条开发问题中有一条排序要求理解错误；人工修订后结果才与已知答案一致。记录见artifacts/live-proposals.json和live-reviewed-runs.json，不是盲测准确率。

```powershell
python -m app.cli import samples/channels.csv
python -m app.cli profile <返回的ID>
python -m app.cli query <ID> "SELECT c1, SUM(c2), SUM(c3) FROM data GROUP BY c1"
```

Python3.12标准库运行，测试需pytest。原始CSV字节与SHA256持久化；原始列名映射为c1…c40，避免列名被误解释为SQL。空白变NULL，首尾空白去除；前导零ID保留文本；小数是浮点近似。公式不执行，不作精确账务用途。

每CSV2MB/10000行/40列、20数据集；查询最多8000字符、200返回行（明确truncated）、约100万虚拟机指令或1秒执行上限。查询只在该数据集的临时内存表上执行，授权回调拒绝写入、附件数据库、系统表、递归查询和非白名单函数；不会执行模型生成Python。限制不构成任意不可信代码沙箱，未来模型只能提出SQL候选。

浏览器已接通列映射/缺失展示、自然语言提议、SQL编辑与确认、结果表格、查询历史和JSON快照下载按钮。条形图按当前结果逐行绘制，最多前20行，不再聚合；数值列含NULL则提示明确处理，不默默丢行。图表不是独立存储的分析结论，SQL与结果快照才是可复现依据。

浏览器实测导入、真实模型错误修订、结果表格、正负值图表与NULL提示，手机390宽无横向溢出；下载落盘仍未验证。需要更多独立数据验证聚合口径；不声称能自动得出可靠业务结论或带来真实业务收益。


## 无需模型的可视化查询

选择分组、统计方式、指标、空值处理、一个筛选条件与排序，点击“生成查询供核对”，再走相同的人工审核和快照流程。支持行数、非空数、非空去重数及数值合计/均值/最小/最大；不会自动执行。数值聚合拒绝文本列，计数方式不接受含糊的补零选项。

POST `/api/datasets/{id}/query-preview` 示例：`{"aggregate":"avg","metric":"c2","nulls":"zero"}`。这一步不使用模型，不创建执行记录。确认后仍需调用 runs；执行快照保存最终 SQL 和审核说明，与手写查询同属非模型查询。

文本筛选保留引号作为值；数字比较拒绝表达式。NULL 分组保留，非空比较不匹配 NULL；范围筛选按列类型比较，文本日期不会自动转换。无匹配行时 SUM/AVG/MIN/MAX 为 NULL。当前仅一个筛选条件，不支持多表连接或可视化复杂公式。生成后可手动修改 SQL，但需要重新核对。

浏览器验收：三行样例订单数为 2、3、NULL，忽略空值均值 2.5，补零均值 1.6666666666666667；筛选搜索渠道金额合计 30。修改选项后重新生成会清除审核勾选及说明，旧结果保持不变。记录见 artifacts/visual-query-browser.json。
