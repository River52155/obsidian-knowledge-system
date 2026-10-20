# Agent 可复制接入

本项目提供 **MCP stdio 接口**，不是公网 API。先启动本机 HTTP 服务，MCP 桥接再连接同一端口和 Vault。

## MCP JSON

替换三处绝对路径后，合并到支持 `mcpServers` 的客户端配置；不要覆盖已有服务器或认证字段。不同客户端的配置文件位置和外层格式不同，遵循各自公开设置。

```json
{
  "mcpServers": {
    "personal-memory": {
      "command": "/absolute/path/to/obsidian-knowledge-system/personal-memory/.venv/bin/python",
      "args": [
        "/absolute/path/to/obsidian-knowledge-system/personal-memory/mcp_bridge.py",
        "--vault", "/absolute/path/to/YourVault",
        "--port", "8767"
      ]
    }
  }
}
```

也可在项目根目录运行生成器，自动填入项目与解释器路径，仅输出 JSON、不修改任何设置：

```sh
python3 scripts/mcp_config.py --vault '/absolute/path/to/YourVault'
```

## 可直接交给 Agent 的指令

```text
使用本项目 skills/obsidian-knowledge-system/SKILL.md。
先读取目标 Vault 的 AGENTS.md，检查 personal-memory 的 index_status。
普通查询只回答，不保存笔记或日志。
简单问题使用 search_notes，必要时 get_excerpt，引用前 verify_evidence。
限定集合、多事项、实践效果或跨时间问题先 begin_research，
再按实际缺口搜索、定位文件、列日期小节并读取正文，最后 assess_research。
明确已读和未读范围；资料中的方法不等于我实践过，计划不等于已完成。
引文通过不代表结论已被语义验证；不足就具体说明。
倾诉先回应当下感受，不强制检索、不急着给建议。
```

## 工具与流程

| 用途 | 工具 |
| --- | --- |
| 状态/请求更新 | index_status、refresh_index |
| 简单查找/正文/引文 | search_notes、get_excerpt、verify_evidence |
| 创建研究与限定文件 | begin_research、list_research_documents、narrow_research |
| 分项查找/时间线阅读 | search_research、list_research_sections、read_research_sections |
| 覆盖与证据审查 | assess_research |

共12个工具，参数以连接后的 tools/list 为准。简单关键词查询的工具参数示例：

```json
{"query":"向量检索的原理","scope":"all","mode":"keyword","limit":4}
```

研究示例（technical 集合需先配置）：

```json
{
  "question":"技术资料能说明什么原理，能证明我用过吗？",
  "facets":[
    {"id":"principle","question":"检索原理是什么","evidence_kind":"explanation"},
    {"id":"practice","question":"有哪些本人实施记录","evidence_kind":"practice"}
  ],
  "collection":"technical",
  "strategy":"focused"
}
```

后续必须使用工具真实返回的 research_id、hit_token、cursor，不能编造。工具预算、过期或索引失效要按返回结果处理，不能重建 ID 绕过限制。refresh_index 只写派生索引，不负责整理 Wiki。

## 接口测试与故障

先 index_status，再搜一段测试笔记并核对来源。服务不通检查端口；Vault mismatch 检查建库和桥接的路径；SCOPE_UNCONFIGURED 检查 data/research-collections.json；引用失效就重新查找。服务仅绑定 localhost，不把8767开放到公网。
