# 日用 AI / Everyday AI

面向个人日常任务的工具页面。SnapText 使用浏览器神经网络 OCR，Cutout 使用本地图片分割模型；另外四款目前只有规划卡片，不是已交付产品。

## 本机运行

在此目录 `npm ci && npm run vendor && npm test`，然后从站点根目录运行 `python -m http.server 8811 --bind 127.0.0.1`，访问 `/everyday/`。不要直接双击 HTML：Worker 与模型需要 HTTP 路径。

`vendor/` 是锁定依赖中生成的分发文件：Tesseract.js 7.0.0、core 7.0.0、中文与英文数据包 1.0.0 的 best_int 数据。三种 LSTM CPU 变体供引擎选择；不使用 Legacy OCR。上述 OCR 资源同域，拾字页面不请求外部模型 CDN，不上传用户图片。生成脚本同时写文件大小与 SHA-256 清单。

## 第一款产品边界

SnapText 支持单图、印刷简体中文和英文、粘贴截图、旋转、原文记录、可编辑结果、复制与 TXT 导出。图片最大 10 MiB / 1600 万像素，处理最长边 2500px。模型准备阶段不能取消；识别阶段可取消。120 秒超时后提示重试；晚完成的引擎会释放。

不支持 PDF、表格重建、手写体保证、语义纠错或自动补写。不保存个人图片和结果；只由引擎缓存模型。引擎置信度不是准确率，识别结果必须核对。OCR 是神经网络推理，不宣称生成式大模型或自研 OCR 模型。

## 来源

- https://github.com/naptha/tesseract.js （Apache-2.0，`vendor/TESSERACT-LICENSE`）
- https://github.com/naptha/tesseract.js-core （见 `vendor/CORE-LICENSE`）
- https://github.com/naptha/tessdata （npm 包元数据声明 MIT；上游训练数据仓库提供 Apache-2.0，原文保存为 `vendor/TESSDATA-LICENSE`。保留两者差异，不把包元数据等同于训练数据许可。）

当前状态：SnapText 首版。9 项自动测试通过；真实中英识别、上传、编辑复制、长图取消重试和 390px 布局已验证，见 `artifacts/RELEASE_CHECK.md`。倾斜与强模糊样例失败已公开保留，手机实机性能尚未验证。调整语言顺序后已无原乱码加载警告；内部根因未定位。

模型/引擎全套分发资源约 16.6 MB，浏览器只下载一种 CPU 核心变体；中英首次所需原始资源约 8.7 MB，网络实际传输取决于压缩与缓存。当前约 0.9 秒的结果是本机开发服务，不能当作公网首次加载耗时。

## 净图 Cutout

构建：`npm ci && npm run build:cutout`。独立 Worker 中运行 IMG.LY 1.7.0、ISNet quint8 和 ONNX Runtime 1.21.0，支持 PNG/JPEG/WebP，输入最多 10 MiB/1600 万像素，处理最长边 1600px。点击才下载 IMG.LY 固定版本 CDN 模型；图片与结果不上传。需要外网下载资源，无离线首次可用承诺。

可取消全部 Worker 任务，180 秒超时可重试。输出透明 PNG，背景色仅用于预览；纯色与完全透明图在推理前拒绝。发丝白边和复杂背景残留仍存在，未提供手工蒙版修复或批量处理。

引擎 AGPL-3.0，见 `vendor/CUTOUT-AGPL-LICENSE.md`；净图相关源文件以同许可提供，第三方来源见 `vendor/CUTOUT-THIRD-PARTY.json`，原始引擎与 ISNet 模型链接保留于其中。其他工具许可不因此改变。已做真实分割、取消重试、透明 PNG 下载、输入失败和窄屏检查；生命周期与输入检查共六项新增测试，整个目录现有 15 项。详见 `artifacts/CUTOUT_CHECK.md`。
