# 固定结构规则 v1 · 2026-09-23

增加 `json-feedback-v1` 与 `json-change-v1` 两个固定规则，编译为 Promptfoo 原生 `is-json` + JSON Schema。规则校验对象顶层、必填字段、字符串长度、枚举、数组上限和额外字段。网页检查规则下拉框可直接选择，保存产生独立测试集版本。

复用依据：[Promptfoo 确定性断言文档](https://www.promptfoo.dev/docs/configuration/expected-outputs/deterministic/#is-json)，并核对本地锁定的0.123.1实现。Schema由代码提供，不接受任意Schema、文件引用或可执行断言。v1定义不应原地修改；将来调整应增加新规则名称，确保历史证据仍可重编译校验。

## 三层验证

- **41项Python测试**通过：本轮增加新规则保存/历史下载、旧原始证据兼容、编译结果修改不污染规则定义、拒绝自定义字段与未知规则等测试。
- **离线重放**：使用同一Promptfoo断言API，原样检查上一轮24个输出和17个边界构造。新增识别 `feedbacklens/1:1` 顶层数组错误。17个边界构造全部符合预期，覆盖合法对象/空数组、缺字段、错误枚举、额外字段、数组上限、长度、null及代码围栏。结果在 `schema-probe.json`。这部分无模型调用，不改写旧运行成绩。
- **真实网页任务**：浏览器从反馈模板保留双问题一例，选择反馈结构v1，保存测试集 `bfa3fd706735423b8e4ca3bc62cd14cf` v1，启动任务 `c7449cefdc7240c79653ce2de5d20e3d`。两次真实模型调用均完成、0调用错误；基线含代码围栏，候选是顶层数组，两者断言失败。浏览器打开对应结果，显示具体原因，两项业务判断仍pending。原始证据在 `schema-live-run`，验收在 `schema-live-acceptance.json`；390px页面scrollWidth375。

离线重放命令：先运行 `python evals/schema_probe.py`，再用安装依赖时的兼容Node执行 `node evals/schema_probe.mjs`。仅固定版本Promptfoo可运行。重放记录结构判断，不重新调用模型；不会把构造样例混入产品准确率。

## 仍未解决的问题

合法结构可能包含编造引用、遗漏条件或错误解释。专门的边界构造 `structure-not-truth` 证明无依据的结论仍可通过结构校验。规则不是原产品完整校验器，也不检查字段之间的业务关系。没有自动剥离代码围栏或修复JSON来提高通过率。结构规则变化与提示词变化应分开版本化，不能将本轮更严格的门槛与旧语法门槛直接比较成模型退步。
