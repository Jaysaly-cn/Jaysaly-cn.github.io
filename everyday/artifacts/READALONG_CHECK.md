# 伴读开发与公开验证

2026-09-24。第四款工具已公开，开发验证与公开站点验收分别记录如下。

## 实际模型

Transformers.js 3.8.1，Xenova/opus-mt-en-zh q8 ONNX，浏览器 WASM Worker 推理，英文到中文单向翻译。七份模型文件来自 ModelScope，按 manifest 所列固定版本和 SHA-256 验证。编码器 52,899,742 字节，解码器 60,212,804 字节，词表约 6.4 MB，总体约 120 MB；运行引擎另从固定版本 jsDelivr 下载。不是托管免费 API，文字不上传。

## 自建样例实测

本机 HTTP、桌面 Chromium；四句含准备 3.1 秒。不是公网首访速度，也未测实体手机。

| 原文 | 模型原始译文 | 人工观察 |
|---|---|---|
| The library closes at 6 p.m. on Friday. | 图书馆于星期五下午6时关闭。 | 时间、日期保留 |
| Do not take this train if you want to go to the airport. | 如果你想去机场,不要搭这班火车 | 否定意思保留 |
| I bought three apples for 12 dollars. | 我买了三个苹果 12美元。 | 数字保留，中文不够自然 |
| When Maya called Anna, she was still at work. | 玛雅打电话给安娜时 她还在工作 | 原文代词歧义仍在，不应自动推断指代 |

首段人工改成“图书馆周五下午六点关门。”后，实际下载 TXT 已核对包含修订和原文。原生确认弹窗测试曾使内嵌浏览器交互持续超时，原因未证实；已改为页面内替换确认，不声称修复浏览器内部问题。

模型准备时取消后重试成功，两段 2.0 秒；分别输出“请带水来”和“公交车星期日不开。”。页面内选择“保留修订”后修订仍在。明确保存词语笔记后，刷新仍保留；短文和译文刷新清空。390×844 浏览器视口单列布局无横向溢出，未测手机实际推理性能。更长文章、部分完成后取消、错误恢复和公网的后续验证见下文。当前 23 项自动测试通过，新增四项覆盖分句顺序、无空白丢词的长句拆分、输入上限及双语导出。

## 扩展样例

以下六句本机含准备 3.2 秒，未人工修改模型输出：

| 原文 | 实际译文 |
|---|---|
| Only passengers with a valid ticket can board the train. | 只有持有有效票的乘客才能上火车。 |
| The entrance is not on the north side of the building. | 入口不在大楼北侧。 |
| Please return the book by next Monday, not this Monday. | 请在下星期一之前归还这本书, 不是本星期一 。 |
| The price is $19.50, including tax. | 价格为19.50美元,包括税收。 |
| I used to walk to school, but now I take the bus. | 我以前走路去上学 但现在我坐公交车 |
| You do not have to finish everything today. | 今天你不必把一切都做完 |

关键否定、金额、时态在这组例句中保留。“by next Monday”译成“下星期一之前”，在截止日是否包含当天的语境里仍需确认。十句人工观察不是标准测试集准确率。

限制：最长 4000 字符、40 段；每段不超过 450 字符，长句按空格拆开可能损失上下文。生成上限 256 token，翻译模型本身可能漏译或误译，不保证结果完整准确。笔记仅在用户点击保存后持久化，短文和译文默认不保存。

## 长文和真实失败验证

20 句、约千字节的自撰社区散步通知，本机模型资源含准备 7.0 秒，全部 20 段有输出。发现以下实质错误，页面也明确列出：

- `You can use the drinking fountain beside the playground.` → `你可以在游乐场旁边用喷泉`，饮水设施译错。
- `Check the weather before leaving home.` → `回家前检查天气`，方向性含义译反。
- `Remember that this is a friendly walk, not a race.` → `记住,这是友好的散步,不是种族。`，多义词译错。

临时移开本机 Worker 分发文件，页面实际收到加载失败后显示错误并解锁原文与重试；随后恢复文件。不是只模拟错误提示。

固定版本 ModelScope 直接分发已在浏览器完成首轮真实推理，含下载 195.2 秒。两句原文 `Please bring water. Do not leave home without your ticket.`，译文分别为“请带水来”和“没有票别离开家”。因此发布方案采用该固定版本下载，不重复存放大权重；配置、来源和校验 manifest 仍保留，脚本可复现下载。

缓存后输入 40 段，在首段生成后实际点击取消：保留 1 段译文和全部 40 段原文，导出按钮可用，其余段落标为未完成。已确认旧任务不会继续填充译文。尚未测试真实八分钟超时、实体低内存手机、模型服务器区域可达性和大量自然文本准确率；无离线首次可用承诺。

## 公网验收

公开地址 https://jaysaly-cn.github.io/everyday/readalong.html ，代码提交 `5661fc576d1b13d6e80bc40f97d7a82c5621ab7f`。Pages 与 Everyday AI 工作流成功；五项公开页面和脚本与仓库逐字节一致。模型通过固定版本 ModelScope 实际下载并在浏览器推理。

公开站点实际输入图书馆与机场两句，耗时 39.8 秒（含准备），结果与上表一致。当前浏览器此前测试过同一模型，缓存可能参与，不能作为全新设备首访速度。首段修订为“图书馆星期五下午六点关门。”后，实际下载的双语 TXT 含原文、修订和第二段译文。取消样例另已下载，文件保留首段译文并含 39 处“未完成翻译”标记。
