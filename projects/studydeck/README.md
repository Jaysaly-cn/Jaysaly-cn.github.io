# StudyDeck

资料驱动的学习卡片工作台：保存原文 → AI 或手工制作草稿 → 人工校对 → FSRS 到期复习 → 导出记录。

这是作品集中的学习场景实验，当前仅本地运行，尚未加入公开陈列馆，也没有真实学习效果数据。

## 启动

Python 3.12，安装 `requirements.txt` 后：

```powershell
$env:SD_MODEL_BASE_URL='http://127.0.0.1:8771/v1'
$env:SD_MODEL='portfolio-qwen-1.5b'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8794
```

打开 http://127.0.0.1:8794 。模型可选，未配置时手工制卡、确认和复习仍可使用。当前适配器只接受本地模型，不产生付费 API 调用。模型会接收选中的完整资料（最多 12000 字符）；上下文过长可能生成失败。

## 工程实现

- FastAPI + SQLite，资料、卡片、事件持久化；默认数据库 `data/study.sqlite3`，可通过 STUDYDECK_DB 覆盖。
- 直接使用 [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) 6.3.2（MIT），不自行重写调度算法。关闭随机扰动；默认目标保留率是调度参数，不是效果承诺。
- 引用必须逐字存在于原文。此检查不能判断答案的语义正确性，确认时仍需人工核对。
- 批量生成全成功才保存，任何引用无效都会回滚；草稿无法评分。
- 确认和评分在 SQLite 写事务内检查版本；重复评分和提前评分返回 409。
- 每次评分保留卡片快照、FSRS review log 和 scheduler 参数；JSON 导出包括全部资料和事件，不重新计算。
- 默认只允许本地 API 请求并拒绝跨源请求。暂不提供公网部署或多用户登录；环境令牌仅适用于 API 客户端，网页尚无令牌输入界面。

## 验证

安装 pytest 后运行 `python -m pytest -q`。Windows 临时目录权限异常时使用项目 data 下新建的唯一 `--basetemp` 路径（先创建 data 父目录）。9 项自动测试：复习事件及重复提交、引用与确认门槛、模型批次原子回滚、数据库重开、评分边界、跨源保护。

## 下一步

已确认卡片修订、资料分组、模型失败可观察性、锁定完整依赖、源码发布及陈列馆案例。导出是备份文件，尚不支持导入恢复。没有把测试通过率写成学习效果。

安全中间件复用本作品集 DataBrief / SupportOps 的 MIT 实现。保留上游 FSRS 的许可信息，见 THIRD_PARTY_NOTICES.md。

## 卡片管理更新

卡片库支持按问题或资料名称搜索、暂停/恢复复习、拒绝/恢复草稿。操作使用版本检查并记录事件，不删除历史；暂停保留 FSRS 状态和原到期时间。队列为空时显示下一次复习时间。新增两项生命周期测试，合计 9 项通过。浏览器已验证暂停和恢复，原计划时间不变；390×844 手机尺寸已验证无横向溢出，并完成拒绝、恢复及问题搜索。见 artifacts/mobile-acceptance.json。

CI 配置见 `.github/workflows/ci.yml`，运行后端测试和 JavaScript 语法检查。该配置尚未推送，不能视为 GitHub CI 已通过。安装测试依赖使用 `pip install -r requirements-dev.txt`。
