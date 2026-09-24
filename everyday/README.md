# 日用 AI / Everyday AI

面向个人日常任务的工具页面。第一款 SnapText 使用真实浏览器神经网络 OCR；其他五款目前只有规划卡片，不是已交付产品。

## 本机运行

在此目录 `npm ci && npm run vendor && npm test`，然后从站点根目录运行 `python -m http.server 8811 --bind 127.0.0.1`，访问 `/everyday/`。不要直接双击 HTML：Worker 与模型需要 HTTP 路径。

`vendor/` 是锁定依赖中生成的分发文件：Tesseract.js 7.0.0、core 7.0.0、中文与英文数据包 1.0.0 的 best_int 数据。三种 LSTM CPU 变体供引擎选择；不使用 Legacy OCR。所有资源同域，页面不请求外部模型 CDN，不上传用户图片。生成脚本同时写文件大小与 SHA-256 清单。

## 第一款产品边界

SnapText 支持单图、印刷简体中文和英文、粘贴截图、旋转、原文记录、可编辑结果、复制与 TXT 导出。图片最大 10 MiB / 1600 万像素，处理最长边 2500px。模型准备阶段不能取消；识别阶段可取消。120 秒超时后提示重试；晚完成的引擎会释放。

不支持 PDF、表格重建、手写体保证、语义纠错或自动补写。不保存个人图片和结果；只由引擎缓存模型。引擎置信度不是准确率，识别结果必须核对。OCR 是神经网络推理，不宣称生成式大模型或自研 OCR 模型。

## 来源

- https://github.com/naptha/tesseract.js （Apache-2.0，`vendor/TESSERACT-LICENSE`）
- https://github.com/naptha/tesseract.js-core （见 `vendor/CORE-LICENSE`）
- https://github.com/naptha/tessdata （npm 包元数据声明 MIT；上游训练数据仓库提供 Apache-2.0，原文保存为 `vendor/TESSDATA-LICENSE`。保留两者差异，不把包元数据等同于训练数据许可。）

当前状态：SnapText 首版。9 项自动测试通过；真实中英识别、上传、编辑复制、长图取消重试和 390px 布局已验证，见 `artifacts/RELEASE_CHECK.md`。倾斜与强模糊样例失败已公开保留，手机实机性能尚未验证。调整语言顺序后已无原乱码加载警告；内部根因未定位。

模型/引擎全套分发资源约 16.6 MB，浏览器只下载一种 CPU 核心变体；中英首次所需原始资源约 8.7 MB，网络实际传输取决于压缩与缓存。当前约 0.9 秒的结果是本机开发服务，不能当作公网首次加载耗时。
