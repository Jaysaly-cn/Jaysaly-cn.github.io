# 临时公开演示 · 2026-09-23

入口：https://derived-miller-allied-enhancement.trycloudflare.com

每位访客获得独立合成品牌活动，走完生成、修订、审核、冻结、JSON/Markdown 下载。不复制私有工作台数据。实验性免费0.5B模型仍会漏说明或编造，不能自动发布。仅使用合成资料；开发机离线或隧道退出后入口不可用，不是稳定云托管。

```powershell
$env:CB_DEMO_HOST='你的确切演示域名'
$env:CB_MODEL_BASE_URL='http://127.0.0.1:8770/v1'
$env:CB_MODEL='portfolio-qwen'
python -m uvicorn app.demo:app --host 127.0.0.1 --port 8807 --workers 1
```

HTTPS代理连接本机8807。只支持单进程；Cookie对应随机独立SQLite文件，HttpOnly/Strict、HTTPS Secure。会话30分钟，最多12个活动空间、每小时30个新会话。单访客60次写请求、3次真实模型尝试（失败计入），全局24次模型尝试/小时，底层60次写请求/分钟守卫保留。输入40KB。模型额度耗尽仍可手工录稿、修订、审核、导出；重启清空内存额度并使Cookie失效，不提供抗持续滥用能力。

精确Host、Origin与跨站写入检查；只有服务端隔离标记可跳过私有令牌检查。私有app.main仍需原访问控制。清理仅专用目录匹配文件；活动请求结束前不删除，20秒定时回收，崩溃残留超过35分钟可回收。无账号、可验证审核身份、团队权限或持久化承诺。

32项自动测试通过，新增6项覆盖跨访客活动、稿件修订、审核、版本对比、JSON/Markdown下载隔离，模型额度与失败计次、手工兜底、过期活动请求、容量和Host/Origin/输入体积保护、全局额度与私有伪造头拒绝。额外验证慢速请求体上传途中会话过期时仍保留数据库，直到请求完成才回收。

公网HTTP真实0.5B生成约2125ms，草稿漏说明被阻断。人工修订已核对F1/F2的合成文案后批准，冻结1份，JSON和Markdown均200；另一访客跨空间请求均404。原始模型稿保留在 ../artifacts/public-smoke.json。复现：python -m evals.public_smoke <已配置演示URL>。不代表生成质量提高。

浏览器独立验证真实生成、修订、审核与冻结；下载内容由HTTP核对，不宣称外部编辑器互通。封装复用同作品集MeetingActions/FeedbackLens MIT实现，保留来源与许可证。
