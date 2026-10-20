# 验证与已知限制

公开导出版本在2026-10-20本机重新执行：

- Python：160项测试通过，约30秒；使用已有 Python 3.11 依赖环境执行导出代码。
- Obsidian 插件：18项测试通过；TypeScript 检查与构建通过。
- MCP：上述测试包含真实 stdio 初始化、工具列表、临时库搜索/读取/来源核对与研究工具调用。
- 新配置生成器：包含空格和中文的临时 Vault 路径输出可解析、路径正确；非法端口被拒绝；不写客户端配置。
- Skill：格式检查和内部参考链接检查通过。

没有在空白电脑重新安装所有依赖，没有重测真实模型问答或原生 Obsidian 点击。向量相关测试含替身，不代表本轮重新下载模型并完成真实向量质量评估。程序测试不等于模型答案准确率。

## 可复现

在安装依赖后的 personal-memory 目录执行：

```sh
.venv/bin/python -m unittest discover -v
cd obsidian-plugin
npm ci
npm test
npm run build
```

独立合成评测位于 acceptance/ 和 evaluate_research.py、evaluate_reliability.py；先看 --help，产物保存在被忽略目录。没有打包早期依赖个人笔记的 cases.json、retrieval-cases.json 和对应历史评测脚本。

## 尚未解决

- 模型仍可能误解日期、文件范围，或把材料扩写成经历/事实。来源核对始终不等于语义裁决。
- 情绪提示允许自然表达，但不能保证文笔、贴心程度或无事实扩写。
- PDF、图片、Word 等附件正文没有自动进入检索；写入流程可用外部提取工具，不能把那项能力等同于检索服务已支持附件。
- 目录允许列表、macOS 托管端口与标签仍有固定约定；未验证跨平台完整安装。
- 不自带账户、模型对话服务或公网鉴权。localhost 检索不代表客户端向模型发送的片段也离线。
- 完整原生长行定位、未保存缓冲区和所有模型回顾场景未逐一人工验证。

导出移除了个人绝对默认路径并泛化称呼；`river.personal-memory` 和 `com.river.personal-memory` 是兼容协议/服务标识，保留以避免破坏桥接，并非凭据。
