# 渠道与必带说明提示对比 · 2026-09-23

## 设计与复现

针对开发中观察到的渠道误写和漏说明，固定两份合成 brief（任务本/笔记工具），每份邮件、短信、小红书三渠道。baseline-v1 逐字复刻当前 app/model.py 提示（不是最初 live-model-baseline.json 的更早提示）；candidate-v2 用 JSON 结构输入，明确渠道不是功能、末尾加说明、不可重复句子。两组 temperature=0.2、max_tokens=650、JSON object 输出约束一致，按每案例 baseline→candidate 顺序串行。分别真实调用本机 Qwen2.5 0.5B/1.5B，共24次。模型与 llama.cpp 部署沿用 LOCAL_MODEL.md。

```sh
python -m evals.prompt_compare --port 8770 --output artifacts/new-comparison-0.5b.json
python -m evals.prompt_compare --port 8771 --output artifacts/new-comparison-1.5b.json
```

仅允许本机8770/8771；拒绝覆盖既有结果。每条保存完整输入、消息、提示SHA256、原始文本（含无效结构）、门禁结果和耗时，逐条落盘。模型和采样参数写入报告，错误记录类型，不把错误移出分母。没有修复模型输出或追加说明后算成功。新增离线测试验证六条 baseline 消息及采样参数与当前生产调用一致。

## 结果

| 模型 | 提示 | 结构与事实ID合法 | 词法门禁全部通过 |
|---|---|---|---|
| 0.5B | baseline-v1 | 6/6 | 1/6 |
| 0.5B | candidate-v2 | 0/6 | 0/6 |
| 1.5B | baseline-v1 | 6/6 | 0/6 |
| 1.5B | candidate-v2 | 6/6 | 1/6 |

0.5B 新提示全部把 title 写成“标题”，没有静默映射字段。0.5B baseline 的唯一词法通过项 notes-邮件写出“不支持给笔记添加标签”，与 F2 明确矛盾。1.5B candidate 唯一词法通过项 tasks-邮件仍有“高效管理”等未被事实直接支持的效果措辞，不能据此批准。其他观察包括虚构第一人称使用体验、重复、漏说明、短信超长，以及引用ID未涵盖全部提及事实。

原始报告里的 semantic_review 保留 pending：没有对24条完成独立盲审评分，以上为开发者可直接定位的定性检查。两份 brief、各提示一次采样、temperature非零、未固定seed、顺序未随机，不能推出泛化准确率或显著改善。原始文件：../artifacts/prompt-compare-0.5b.json 与 prompt-compare-1.5b.json。

**决策：不替换当前模型与提示。** 新提示尚未达到稳定使用标准。保留原稿、规则阻断和人工逐句审核，继续扩大案例后再判断。

## 从失败落到编辑流程

新增“补入必带说明后编辑”：只把活动原文说明追加到修订编辑器，明确显示尚未保存。用户可继续编辑、取消或保存。保存沿用既有版本冲突检查、重新跑规则与人工审核，旧版本和旧交付包不变；不把这项确定性编辑伪装成模型改进。

26项自动测试通过，其中新增2项验证补入说明后仍待审核、未勾事实核对不能批准、短信补说明后超长仍阻断；另1项验证评测baseline与生产请求一致。真实浏览器对上一轮0.5B邮件失败稿补入说明，保存人工v2，旧稿保留，规则通过但语义问题仍存在，明确未批准。冻结Markdown与旧文件相同。证据见 ../artifacts/required-revision-browser.json。
