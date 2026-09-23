# FeedbackLens

目标：帮助产品经理把 CSV 用户反馈整理为有原文依据的主题，并记录人工归类、重复判断和报告口径。当前已完成可运行的网页工作台、本地免费模型建议、人工归类及重复判断、冻结报告；本地单人工作台，源码与案例已公开。

## 当前可运行

Python 3.12，安装 requirements.txt 后：

```
python -m app.ingest samples/feedback.csv --db data/feedback.sqlite3
```

导入上限 1MB / 500行，UTF-8 CSV 列固定为 source_id、channel、text。source_id 在工作台内唯一；重复导入同一条不会膨胀计数，同一 ID 对应不同内容会整体回滚。保存文件 SHA256、原始 CSV、原文、渠道、行号和导入关联。不同 ID 的同文反馈仍保留：可能来自不同用户，不能自动当重复删除。

RapidFuzz 3.14.6 用字符相似度给出前10个候选，不自动合并、不是语义相似度，也不用于产品优先级。最多比较工作台最近500条反馈；当前数据库最多500条，超限拒绝而非静默截断。资料仅本地保存。

后续开发见 PRODUCT_PLAN.md：真实后端、免费模型分类建议、人工证据归类、冻结报告、网页工作台与失败样例。网页工作台已可使用，接入本地免费模型，实测输出仍需人工修正。

## 人工归类 API

启动 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8796`，本地接口文档在 /docs。支持 POST /api/imports 原始CSV、GET /api/feedback、GET /api/similar?source_id=、POST /api/annotations（source_id/theme/kind/quote）、POST /api/annotations/{id}/review（version/decision/note）以及 POST /api/reports（title/note）。报告 GET /api/reports/{id} 返回冻结快照。未审核草稿不参与汇总；每主题/总览均按 source_id 去重计数，多个来源 ID 的同文内容仍分别保留，不等同独立用户数。主题合理性由审核者判断，引用校验不判断语义。

10 项测试通过，实际 HTTP 验收 4 条合成反馈、1 条人工确认归类及1份冻结报告，见 artifacts/manual-api-acceptance.json。安全中间件复用本作品集 StudyDeck/SupportOps。当前默认本地单人服务，不提供公网多用户隔离。

## 免费模型建议

设置 FL_MODEL_BASE_URL=http://127.0.0.1:8771/v1 和 FL_MODEL=portfolio-qwen-1.5b 后启动。POST /api/suggestions（source_id）对单条反馈提出最多5条草稿，GET /api/model-runs 查看原始输出及失败类型；最多保存100次运行。引用不精确时整批拒绝，成功也不自动确认。

14项测试通过。真实模型两条合成样例：s4多诉求被合并并改写引用，返回422；s3否定意见引用正确但主题为占位词“简短主题”，仅进入草稿，不参与报告。这不是两条正确，也不是准确率基准。原始记录见 artifacts/model-live.json。模型接口复用StudyDeck的本地免费端点约束，不产生付费API请求。模型功能尚未发布。

## 网页工作台

启动后打开 http://127.0.0.1:8796 。支持CSV文件导入、反馈搜索、相似候选查看、模型提议、手工归类、修订/审核/拒绝及历史查看、模型原始输出、报告冻结和JSON导出。修订会退回草稿，旧报告仍不变；编辑未保存时不能审核旧版本。

16项测试通过。浏览器用已有真实模型坏例，将s3占位主题改成“反对新增离线导出”，保存后审核并冻结：4条总反馈、2条已确认，反对意见与导出入口问题各1条。证据见 artifacts/browser-review.json。浏览器CSV重复文件导入和390px手机布局已验收，见下文。下载落盘尚未验证。

## 导入与手机验收

浏览器实际选择 samples/feedback.csv 重复导入，显示新增0、复用4，同文件未重复计数。导入提示现区分新增与复用。390×844视口下，反馈搜索/选择和冻结报告证据展开均无横向溢出（文档宽375）。证据见 artifacts/import-mobile-acceptance.json。CI配置已添加，但尚未公开运行；本地16项测试通过，JavaScript语法检查通过。


## 人工重复判断与计数

选择反馈后展开“标记或撤销重复收录”，指定代表反馈并填写原因；改回独立保留即可撤销。POST /api/duplicates 接收 source_id、target_id（撤销为 null）、version（首次0）、note；GET /api/duplicates 读取当前判断，GET /api/duplicates/{source_id}/history 查看历史。写入事务和版本检查避免覆盖旧判断；禁止自指、链式和循环标记。原文及归类不删除。

新报告保留原始 total_feedback、confirmed_feedback、各主题 feedback_count，同时提供 deduplicated_total_feedback、deduplicated_confirmed_feedback、各主题 deduplicated_feedback_count 和代表ID。每个主题独立计数，主题数量不能相加作总数。代表记录可以没有自身归类，代表ID仅用于计数，不把其他记录的主题移植给它。两种数量都不是人数或商业优先级。报告冻结当时判断；撤销不改写旧报告。

22项本地测试通过，JavaScript语法检查通过。浏览器合成验收：标记后总量4→3，撤销后新报告恢复4，旧报告仍为3；详见 artifacts/duplicate-browser-acceptance.json。测试覆盖版本冲突、非法目标、循环/链式拒绝、事务回滚和跨主题证据保留。尚未公开发布，无真实用户效果数据。


## 发布验证范围

当前24项自动测试通过，包含真实模型输出回放。新增讽刺探针提取“加载速度”问题；嵌入指令探针生成了“忽略规则”“表扬”等错误主题，全部停留草稿，没有执行或发布操作。原始记录见 artifacts/model-additional-probes.json；不能把引用校验通过视为语义正确或抗注入保证。可运行 `python -m evals.live_probes` 生成独立测试记录（已有证据时拒绝覆盖；需本地模型）。此前段落测试数量是各开发阶段记录。

安装与验证：`pip install -r requirements.txt -r requirements-dev.txt`，然后 `python -m pytest -q` 和 `node --check web/app.js`。源码镜像发布于个人主页仓库 projects/feedbacklens，不是独立远程仓库。动态后端仅本地可用，没有稳定公网服务；所有验收资料为合成数据，没有真实业务效果数据。

## 提示词实验与运行追溯

6条合成反馈、12次实际模型调用对比见 artifacts/prompt-comparison-review.md。候选改善部分引用与多诉求拆分，但仍存在指令污染、否定及条件主题问题，因此默认继续使用v1，未宣称质量已达标。新模型记录保存模型名、提示词版本和SHA256，历史缺失字段明确显示未知；这些参数不构成完全复现保证。

本地26项测试通过，新增失败请求参数留存和旧数据库幂等迁移验证。源码包含运行追溯功能，浏览器验证见 artifacts/provenance-browser.json。


## 手机重复判断与模型记录

390×844浏览器视口实测发现模型哈希造成608px横向溢出；增加长文本换行及网格最小宽度约束后恢复375px文档宽。已实际保存重复标记、撤销并展开历史，三处均无横向溢出。记录见 artifacts/mobile-duplicate-acceptance.json。这是视口模拟，不是实体手机兼容性认证。
