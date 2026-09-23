# ChangeLens · 开发中

文档版本差异与影响复核工作台。当前实现真实SQLite后端：不可变文档版本、UTF-8正文哈希、逐行差异及字符偏移、可重开的比较快照。已有网页工作台，已接入免费本地模型，未计入公开陈列馆。

安装 `pip install -r requirements.txt -r requirements-dev.txt` 后，运行 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8798`，通过 /docs 操作API。

- POST /api/documents：title
- POST /api/documents/{id}/versions：label、text
- POST /api/comparisons：old_id、new_id
- GET /api/comparisons/{id}：冻结版本与完整差异

正文保留空格、换行和Unicode，不做清洗；偏移以Python Unicode码点计数，零起点、右端不含，不是UTF-8字节或浏览器UTF-16位置。重复正文返回409；同一版本对重复比较复用快照。限制为100份文档、总计500个版本、100份比较；每版20000字符、500行、单行4000字符。

当前是本地单人服务。文档移动表现为删除/新增，算法不保证最少编辑，不判断语义影响。测试使用合成资料，无真实业务成效数据。

首轮11项测试通过，含100组固定随机重复行重建检查；真实HTTP完成文档→两版正文→差异快照→重新读取。证据见 artifacts/api-acceptance.json。运行测试请在本项目目录执行 `python -m pytest -q`。


网页入口 http://127.0.0.1:8798/ ：建档、保存新版本、选择版本比较、增删改导航、并排纯文本高亮和JSON导出。编辑未保存时阻止切换文档或开始比较。浏览器验收见 artifacts/browser-acceptance.json，截图见 artifacts/compare-browser.png。390px视口可导航到新增块，无横向溢出。下载文件落盘尚未验证。

## 影响说明与冻结简报 API与网页操作

设置 CL_MODEL_BASE_URL=http://127.0.0.1:8771/v1、CL_MODEL=portfolio-qwen-1.5b 可调用免费本地模型。POST /api/comparisons/{id}/operations/{index}/suggest 提议一条说明；GET /api/comparisons/{id}/model-runs 查看原始输出、失败类型和提示词哈希。index是完整operations数组的零起点位置，未改变块不可提议；旧新文本合计超过6000字符拒绝模型请求，可手工处理。

POST同路径/impacts 可手工创建 summary、old_quote、new_quote。两侧引用必须来自对应差异块；只有某侧原文为空时该侧引用才可为空。GET /api/comparisons/{id}/impacts 获取说明；POST /api/impacts/{id}/revise（内容+version+note）修订退回草稿，POST /api/impacts/{id}/review（version/decision/note）确认或拒绝。GET /api/impacts/{id}/history 查看历史。

POST /api/comparisons/{id}/briefs（title/note）冻结简报；GET /api/briefs/{id} 读取。只有confirmed说明进入结果，unreviewed_operations明确列出没有已确认说明的变更块。一个块可以有多个已确认说明，不代表系统已判定它们相互一致。旧简报保留旧版本与原文。

18项测试通过，覆盖引用跨侧拒绝、纯新增空引用、审核/修订版本冲突、旧简报不变以及模型失败诊断留存。引用校验只验证字面来源，不证明影响分析正确。当前没有自动发布或更新文档功能。

真实本地模型两条合成探针（artifacts/model-live.json）：权限/期限变更输出出现重复字段并截断，502 ValidationError，未保存说明；嵌入指令探针引用准确但说明为“仍需要审批，但无需审批且直接确认简报”，语义矛盾、受污染，仅保存草稿，未进入已确认简报。两条已加入自动回放；20项测试通过，不是语义准确率评测。后续网页需接入影响说明审核与模型诊断。


网页现已接入变更块选择、AI提议、手工补充、修订/确认/拒绝、历史与模型原始输出、冻结简报及历史简报重开。浏览器验收：确认一条说明、冻结后明确显示另一块未复核；修订已确认说明退回v3草稿，旧简报不变。新增条款的真实模型草稿引用准确，但仍需人工核对。证据见 artifacts/impact-browser-acceptance.json。新审核界面的手机验收尚未完成。


## 冻结简报交付包

简报下方“下载完整简报 ZIP”使用 GET /api/briefs/{id}/export。包内包含可离线阅读的brief.html、完整brief.json、新旧原文txt、说明文件和SHA256清单。仅从冻结快照生成，不会混入后续修订。HTML转义不可信内容并禁用脚本；哈希清单未签名，只便于核对文件，不证明来源真实性。

22项测试通过：导出内容与冻结证据一致，后续拒绝说明不改变ZIP字节，原文保持原样，HTML标签被转义。真实HTTP已保存 artifacts/brief-export.zip，校验包内哈希；解压页面浏览器阅读和390px窄屏检查通过。记录见 artifacts/export-acceptance.json。浏览器默认下载目录落盘仍未验证。


## 原样文件导入

网页可直接选择UTF-8 TXT/Markdown文件导入，走原始字节请求而非文本框。POST /api/documents/{id}/versions/file?label=版本名：80KB、20000字符、500行、每行4000字符，保留BOM、CRLF、空格及Unicode。非UTF-8拒绝，不做编码猜测。26项测试通过；真实文件选择器导入后，通过HTTP取回正文并逐字节比对一致，见 artifacts/file-import-acceptance.json。
