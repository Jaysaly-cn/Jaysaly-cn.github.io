# Jaysaly's personal homepage

俞凯杰的独立静态个人主页，部署目标为 `https://jaysaly-cn.github.io/`。

## AI Demo Lab

`demos/` 提供六项无需后端的交互演示：

- CoAgents Agent 运营闭环案例
- 豆田节肢动物目标检测标注可视化
- 夜蛾科昆虫识别结果与分类路径
- 蛋白 FASTA 序列解析与组成特征
- AgriWorld 农业世界模型环境因子与反事实轨迹可视化
- 植保智能体多 Skill、RAG、诊断仲裁与安全护栏工作流

视觉任务使用项目仓库中的真实样例数据；蛋白任务仅对内置测试样例展示已知标签。农业世界模型与植保智能体页面是基于真实项目机制设计的交互产品原型。真实模型推理仍需独立部署 API，GitHub Pages 不承载模型权重、数据库或密钥。

## 本地预览

在此目录运行：

```powershell
python -m http.server 8080
```

然后访问 `http://localhost:8080/`。

## 发布

该仓库无需构建。将 `main` 分支推送到 GitHub 上名为 `Jaysaly-cn.github.io` 的公开仓库，并在仓库设置中选择 **Deploy from a branch → main / (root)**。
