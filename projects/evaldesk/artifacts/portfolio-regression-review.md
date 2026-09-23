# 跨项目回归基线 · 2026-09-23

从 FeedbackLens 与 ChangeLens 已有合成开发记录中固定各六例，两套原始提示词，共24次真实 Qwen 1.5B 调用，0调用错误。完整来源、上游提交、文件哈希及提示词哈希见 `samples/portfolio-provenance.json`。全部是已知样例，不是留出集或独立盲测。

| 产品 / 方案 | 有效 JSON | 业务复核接受 | 待复核 |
| --- | --- | --- | --- |
| FeedbackLens baseline | 2/6 | 0/6 | 0 |
| FeedbackLens candidate | 2/6 | 0/6 | 0 |
| ChangeLens baseline | 0/6 | 2/6 | 0 |
| ChangeLens candidate | 2/6 | 1/6 | 0 |

业务复核由同一 AI 开发代理按预先保存的判据逐例完成，不代表独立人工评审或真实业务准确率。复核理由与冻结报告分别在 `feedbacklens-regression-review.json`、`changelens-regression-review.json`。`accepted` 仅表示该条业务内容符合记录的判据，不覆盖自动格式失败，也不表示可以直接交付。

## 关键发现

- FeedbackLens 候选的双问题输出是顶层数组，虽通过 is-json，仍违反要求的对象结构；指令污染样例也能通过 JSON 检查。下一步应引入受限字段/结构验证，但仍不能替代语义判断。
- ChangeLens 候选在权限案例遗漏期限变化，在指令案例产生审批矛盾；这两例恰好都通过 JSON 检查。两套提示词均不能靠格式指标批准上线。
- ChangeLens 三条业务内容正确的输出带有 Markdown 围栏，因而格式不通过。原样保留，不自动清洗以美化指标。

## 新基线的运行边界

EvalDesk 使用 temperature=0、max_tokens=500，没有原工具的 `response_format=json_object`。ChangeLens 两套方案都使用相同 old_text/new_text 输入，原工具 baseline 则使用完整差异对象。因此这轮不是历史运行的等环境复现，不能直接比较旧通过率。不同产品的业务判据也不相同，不计算合并的产品质量分数。

两轮原始文件分别保存为 `feedbacklens-regression-run/` 与 `changelens-regression-run/`：测试集、编译配置、原始响应、日志、哈希清单。`evals/review_portfolio_baseline.py` 是对这两个固定运行的开发者判断记录，不是自动语义评分器；遇到已有复核会拒绝覆盖。公开报告不依赖运行中的数据库。

## 示例库与验收

测试集工作室提供三种模板：工单路由、反馈回归、变更回归。模板读取使用固定允许列表，不允许文件路径。读取不写数据库；显式保存创建独立版本，不调用模型。回归模板均为六例、两方案，12次计划调用，符合临时演示单任务额度。

37项自动测试通过。浏览器实际保存两组版本；编辑后切换模板被阻止，原草稿保留。390px视口 scrollWidth=375，截图 `regression-library-mobile.png`。公网 HTTP 实际读取并保存两种模板，任务仍为空，记录 `regression-library-acceptance.json`。本轮24次模型调用通过本机CLI执行，不声称通过公网重新运行这24次。
