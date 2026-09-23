# 来源与复用记录

- 产品调研：Inbox Zero, https://github.com/elie222/inbox-zero ，2026-09-23访问。它提供邮箱助手、回复跟踪、分类与附件管理，技术栈含Next.js/Prisma。当前仅作产品参考，没有复制其源码、图形或品牌，也不将其成果声称为本项目原创。许可证原文：https://github.com/elie222/inbox-zero/blob/main/LICENSE 。若后续移植代码，记录具体提交、路径和适用声明。
- 邮件解析：Python 3.12标准库email，https://docs.python.org/3.12/library/email.message.html 。调用标准库API，无粘贴文档实现。
- 本项目SQLite连接写法沿用同作品集MeetingActions的MIT代码模式，作者Kaijie Yu。正文转换、导入事务与CLI为本项目开发。
- app/security.py改编同作品集MeetingActions的MIT单机访问保护，改用INBOXTOTASKS_ACCESS_TOKEN和2MB输入限制；保留来源文件说明。
- app/model.py改编本作品集MeetingActions MIT本地/免费模型适配器。已复用本机Qwen2.5-1.5B-Instruct Q4_K_M（现有local-model-runtime/qwen-1.5b.gguf）与llama.cpp b11118服务，模型来源和校验记录沿用local-model-runtime；没有下载新权重。该模型输出存在改期漏提，原始结果单独记录。模型与运行时的许可证不由本项目MIT替代。
