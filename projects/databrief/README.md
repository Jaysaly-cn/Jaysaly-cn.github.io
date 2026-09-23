# DataBrief v0.3 · 运营数据分析台

第七款作品，目标为CSV→数据质量概览→自然语言分析问题→可检查的SQL→结果与图表快照。

目前完成UTF-8 CSV导入、数据概览、只读受限SQL、持久化结果、FastAPI、免费本机模型SQL提议和浏览器表格/图表工作台。启动后打开 http://127.0.0.1:8792 ，可通过“打开合成渠道数据”体验。[产品案例](https://jaysaly-cn.github.io/cases/databrief.html)提供流程与验证记录；动态工作台仍需本机启动。

后端：`pip install -r requirements-lock.txt`，运行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8792`。模型配置 `DBR_MODEL_BASE_URL=http://127.0.0.1:8771/v1` 与 `DBR_MODEL=portfolio-qwen-1.5b`，需先启动相应本地推理服务。访问令牌 `DATABRIEF_ACCESS_TOKEN`；无令牌时仅允许本机访问。

API：POST `/api/datasets?name=名称` 上传CSV字节；GET `/api/datasets/{id}` 查看概览。POST `/api/datasets/{id}/proposals` 提交question，仅保存提议，不执行。POST `/api/datasets/{id}/runs` 提交sql、可选proposal_id、reviewed=true、至少5字note，经受限执行器运行。GET同一路径读取历史；GET `/api/runs/{id}` 下载固定JSON快照。

提议原文与实际执行SQL分别保留；修改查询不改写原提议。模型只接收列映射/名称/类型/缺失计数、总行数与问题，不发送单元格样例或行值。最多30次模型提议/数据集；协议错误保留raw。仅允许本机或明确OpenRouter免费型号，未自动购买额度。

46项测试通过，`node --check web/app.js`语法通过。真实Qwen1.5B三条开发问题中有一条排序要求理解错误；人工修订后结果才与已知答案一致。记录见artifacts/live-proposals.json和live-reviewed-runs.json，不是盲测准确率。

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


## 结果交付包

成功查询可以下载 ZIP：`GET /api/runs/{id}/bundle`，包括 UTF-8 BOM 的 CSV、实际执行 SQL、带审核说明和来源哈希的 JSON 快照及导入说明。导出读取保存的结果，不重新执行，不包含原始数据集或其他历史。截断结果的表名为 result-truncated.csv，说明中也明确警示。

CSV 的 NULL 写为 `\N`；空字符串保持空单元格，同名列与顺序保留。文本中可能作为公式的前缀会加单引号，数值负数保持数字。CSV不是无损类型格式：原文本身为 `\N`、前导零编码、大整数、日期等请用JSON核对，并在表格软件中选择文本导入。JSON保留原值。失败查询仍可下载JSON，不能导出结果表；二进制SQL结果会被明确拒绝并记录失败。

40项自动测试通过；真实HTTP导出及解包检查通过，浏览器按钮已发起下载且无错误日志，但浏览器最终文件落盘仍未确认。HTTP取得的合成样例包在工作区 portfolio-optimization/databrief-sample-result.zip。


## 临时公开演示

[打开临时工作台](https://ham-adware-ancient-moms.trycloudflare.com)。这是开发机上的短期演示，非稳定云托管；离线或隧道重启时可能失效。每位访客独立数据库、30分钟会话，预置合成渠道数据；可视化查询无需模型。请仅使用合成资料并及时导出结果。

独立启动：`DBR_DEMO_HOST` 设置为确切公网域名，运行 `python -m uvicorn app.demo:app --host 127.0.0.1 --port 8793`，仅允许单进程。模型仍使用 DBR_MODEL 系列配置。不要将私有 app.main 进程直接接入公开隧道。演示目录默认 data/public-demo，和私有数据库分开；仅在该目录清理自身命名的会话文件。重启令所有会话失效。

每会话最多60次写入、3次模型请求；全进程12个会话、每小时30次新会话及24次模型请求，单次输入40KB。模型失败也消耗配额；额度耗尽仍可使用可视化查询。限额依赖单进程内存，不是通用多租户生产系统。

46项测试覆盖原有功能和新增的访客隔离、导出越权、伪造请求头、来源/域名校验、过期清理、容量与模型配额。公网验收 `python evals/public_smoke.py <公网地址> --model` 会创建两份合成会话；记录见 artifacts/public-acceptance.json。一次真实模型把忽略NULL写成COALESCE补零，全部NULL情况下语义不同，故未自动执行或计为正确。浏览器可视化查询实测合计60，无控制台错误。

## 演示会话可靠性更新

当前完整测试共 49 项通过。修复慢上传途中会话过期时提前清理数据库的问题，新增正常上传、超限与额度拒绝回归。[复现与范围](docs/DEMO_UPLOAD_FIX.md)。此前章节中的测试数量是对应版本的历史记录。
