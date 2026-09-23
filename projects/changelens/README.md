# ChangeLens

文档版本差异与影响复核工作台：原始版本 → 逐行对比 → AI 草稿或手工说明 → 人工审核 → 冻结简报与 ZIP 交付。FastAPI、SQLite、原生浏览器界面；本地免费 Qwen 1.5B 可选，无模型时核心流程仍可用。

[公开案例](https://jaysaly-cn.github.io/cases/changelens.html) · [临时在线体验](https://listprice-cancellation-airline-natural.trycloudflare.com)

## 启动

需要 Python 3.12。在本项目目录执行：

```sh
pip install -r requirements.txt -r requirements-dev.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8798
```

打开 http://127.0.0.1:8798/，API 文档位于 /docs。默认数据库 data/change.sqlite3，可设置 CHANGELENS_DB。设置 CHANGELENS_ACCESS_TOKEN 后 API 需要 Bearer 令牌；内置网页没有令牌登录界面，默认用于本机单人操作。

可选本地模型配置：CL_MODEL_BASE_URL=http://127.0.0.1:8771/v1、CL_MODEL=portfolio-qwen-1.5b。仅允许 localhost/127.0.0.1/::1 模型端点；仓库不包含模型权重或运行器。兼容 chat/completions 接口的本地服务需自行启动。

## 使用流程

1. 建立文档，输入或导入至少两个版本。文件支持 UTF-8 TXT/Markdown，保留 BOM、CRLF、空格和 Unicode；文本框使用浏览器标准换行。原文不可覆盖，重复内容返回409。
2. 选择旧版与新版比较。移动段落可能显示为删除和新增，算法不保证最少编辑；变更块数不等于业务事项数或风险分数。位置按 Python Unicode 码点计数，零起点、右端不含。
3. 对变更块请求 AI 草稿或手工说明。引用必须逐字来自对应侧的连续原文，空白侧才可留空。模型输出与失败原因保留。修订已确认说明会退回待审核，旧版本操作返回冲突。
4. 确认或拒绝说明，填写范围后冻结简报。只纳入已确认说明，并列出没有已确认说明的变更块。一个块允许多条已确认说明，不代表系统验证过相互一致性。
5. 下载 ZIP：brief.html、brief.json、新旧原文、说明及 SHA256 清单。历史简报不会被后续修订改写；HTML 转义并禁用脚本。哈希清单不是签名，不证明来源真实性。

本地容量：100份文档、总计500版本、100比较、1000说明、100模型记录、100简报。每版最多20000字符、500行、每行4000字符；文件最多80KB。模型单个变更块双侧合计最多6000字符。

## 临时访客演示

复用本作品集 FeedbackLens 的 MIT 隔离入口。运行 python -m uvicorn app.demo:app --host 127.0.0.1 --port 8799，只能使用单进程；远程域名需配置 CL_DEMO_HOST 为精确主机名。代理部署时仅信任实际反向代理地址。

每位访客独立 SQLite 数据库，预置两个合成版本；30分钟过期，后台每20秒清理已过期且无活跃请求的数据库。重启使会话失效。最多12个同时会话、每小时30个新会话、每会话60次写入、3次模型请求、全局每小时24次模型请求。失败也占额度；单次输入40KB。额度不足时可手工说明、审核和导出。Cookie 使用 HttpOnly、SameSite=Strict，HTTPS 时启用 Secure；跨站请求及未知 Host 拒绝。

公开入口依赖开发机与临时隧道在线，可能失效，不是稳定云服务。仅使用合成资料，输入在演示服务器处理。不要用多 worker 部署这一内存会话方案。

## 验证与已知问题

运行 python -m pytest -q 和 node --check web/app.js。当前31项测试通过，包括原文重建、版本不可变、引用边界、状态冲突、冻结与导出、文件编码、访客隔离、过期清理和额度。

- artifacts/model-live.json：两条真实合成探针，分别出现重复字段截断、引用通过但解释受文档指令污染。不是准确率评测，引用通过不证明语义正确。
- artifacts/impact-browser-acceptance.json：浏览器手工确认、冻结、修订重审与旧简报不变；新增条款的另一次真实模型调用保存草稿。
- artifacts/file-import-acceptance.json：实际文件选择器导入后，HTTP取回正文的 UTF-8 字节与 CRLF 原文件一致。
- artifacts/review-mobile-acceptance.json：390px视口打开比较和历史简报，展开完整证据，无横向溢出；不是实体手机兼容认证。
- artifacts/export-acceptance.json：真实 HTTP 导出 ZIP 校验与离线 HTML 阅读。浏览器默认下载目录落盘尚未验证。
- artifacts/public-acceptance.json：公网双访客隔离、手工审核与 ZIP 导出通过；模型省略引用中的换行，被拒绝保存。
- artifacts/public-browser-acceptance.json：公网浏览器比较、手工说明、确认及冻结流程。

仅支持纯文本，不解析PDF/Word，不自动执行文档指令、不自动确认或发布。没有真实客户访谈与运营成效数据。

## 来源

借助 AI 编程协作开发。研究了 [Redlines](https://github.com/houfu/redlines) 的文本差异形式，没有复制或安装其代码；差异使用 Python 标准库 difflib。模型适配、服务保护及访客隔离复用本作品集已有 MIT 项目，保留项目 LICENSE。源码作为个人主页仓库 projects/changelens 的项目目录发布。

## 提示词对比与原文辅助

对六条预先固定的合成样例做12次真实调用，候选方案格式/引用门槛5/6、基线4/6，但仍存在指令污染和条件漏提，故保留默认v1。见 artifacts/prompt-comparison-review.md 与 prompt-comparison-v2.json；不是独立盲测或语义准确率。可设置上述本地模型环境变量后执行 python -m evals.compare_prompt artifacts/new-comparison.json 重跑，脚本拒绝覆盖已有证据。

手工说明新增“填入此块原文引用”。未编辑引用保留原始CRLF等换行，浏览器显示可能标准化；编辑后按实际输入校验。说明未保存时阻止切换变更块，撤销后可切换。单侧超过4000码点需手选片段。实际浏览器保存、修订及确认后，通过HTTP核对CRLF仍在，见 artifacts/quote-helper-browser.json。
