# 日用 AI：六款 ToC 工具

2026-09-24。独立入口：[日用 AI](https://jaysaly-cn.github.io/everyday/)。保留原 ToB 工程陈列馆，主页只提供两个入口。无注册、无付费 API 密钥；实际模型在浏览器运行。不是预设答案演示，也不是自研基础模型。

| 工具 | 可完成的个人任务 | 实测记录 |
|---|---|---|
| [拾字 SnapText](https://jaysaly-cn.github.io/everyday/snaptext.html) | 图片中文字提取、编辑、复制、TXT | [识别质量与困难样例](artifacts/RELEASE_CHECK.md) |
| [净图 Cutout](https://jaysaly-cn.github.io/everyday/cutout.html) | 去背景、底色预览、透明 PNG | [人物分割与边缘问题](artifacts/CUTOUT_CHECK.md) |
| [听写 ClipScribe](https://jaysaly-cn.github.io/everyday/clipscribe.html) | 两分钟内音频转录、修订、回听、SRT/TXT | [分块、静音与幻觉](artifacts/CLIPSCRIBE_CHECK.md) |
| [伴读 ReadAlong](https://jaysaly-cn.github.io/everyday/readalong.html) | 英译中对照、修订、词语笔记、双语 TXT | [长文与实质误译](artifacts/READALONG_CHECK.md) |
| [今晚吃什么 Pantry](https://jaysaly-cn.github.io/everyday/pantry.html) | 有来源菜谱推荐、份数计算、一餐缺料清单 | [偏好变化、数据核对与导出](artifacts/PANTRY_CHECK.md) |
| [周末半径 DayPlan](https://jaysaly-cn.github.io/everyday/dayplan.html) | 自选地点偏好匹配、约束排程、调整、TXT/ICS | [时间冲突、无解与日历格式](artifacts/DAYPLAN_CHECK.md) |

## 选题与可展示能力

[行业调研](RESEARCH.md)覆盖助手搜索、视觉、音视频创作、语言学习、文件处理、饮食、出行与陪伴娱乐。首批取可验证输出、免费本地推理、个人任务频率三个维度，选择六个有完整输入和导出的场景。这是桌面研究与工程取舍，未完成访谈、市场规模估算、留存或付费意愿验证。

作品展示重点：输入约束、异步模型生命周期、进度/取消/恢复、人工修订与数据导出；以及 AI 排序与确定性约束分工、原始来源和失败样例公开。源码、固定版本、依赖许可与自动检查一起提供，便于复现。开发命令见 [README](README.md)，持续集成见仓库 `.github/workflows/everyday.yml`。

## 运行成本与已知限制

首次访问需要下载模型。OCR 中英所需原始资源约 8.7 MB；听写模型约 43.6 MB；伴读约 120 MB；餐单与日程共用的语义模型及词表约 135.4 MB。净图采用固定版本外部模型服务。浏览器缓存、设备内存和网络会显著影响等待时间，不承诺首次离线或所有区域可达。

识别倾斜与模糊图、抠图发丝边缘、音频噪声幻觉、翻译多义词都有已公开的失败结果。餐单仅含 12 道菜且库存只记有无；日程不提供地图导航、实时营业或价格。结果允许核对与修订，无法替代相应专业判断。

36 项自动测试通过；各工具已有桌面真实推理、导出及 390px 布局检查。窄视口不等于真实手机评测，尚无实体手机矩阵或大规模用户效果数据。输入默认不持久化，伴读词语笔记仅在主动保存后存入本机；模型可被浏览器缓存。
