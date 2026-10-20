# 从零安装

以下在独立新目录操作。已有生产服务先核对端口与备份，不同时启动两个8767实例。

## 1. 下载项目与安装依赖

```sh
git clone https://github.com/River52155/obsidian-knowledge-system.git
cd obsidian-knowledge-system/personal-memory
uv venv .venv --python python3.11
uv pip install --python .venv/bin/python -r requirements.lock.txt
.venv/bin/python semantic_search.py download
```

`uv` 和 Node 需自行先安装。模型下载需要网络，后续本机加载不需要远程模型代码。

## 2. 建立索引

先确认 Vault 中哪些目录属于允许范围（见根 README）。下面路径替换为自己的绝对路径：

```sh
.venv/bin/python memory_search.py build --vault '/absolute/path/to/YourVault'
.venv/bin/python semantic_search.py build
mkdir -p data
cp ../examples/research-collections.json data/research-collections.json
```

集合样例需按自己的已索引路径检查后使用；technical 不包含整个 Wiki，避免把日记当技术资料。allowed 表示允许集合，不代表全电脑。Raw 和保护目录不进入索引。初建命令只用于离线初始化，服务运行后的更新用“检查更新”。

## 3. 启动与确认

```sh
.venv/bin/python memory_search.py serve --port 8767
```

保持终端运行，另一个终端检查：

```sh
curl --fail http://127.0.0.1:8767/api/health
```

然后打开 http://127.0.0.1:8767 。服务使用数据库中保存的 Vault 路径，`serve` 没有 `--vault` 参数。health 返回只表示服务状态，还要用合成内容验证检索。

可选 macOS 托管：停止手动进程后，在 personal-memory 运行 `.venv/bin/python service_control.py install`。此脚本固定端口8767和标签 `com.river.personal-memory`，同一用户不要用它部署第二套实例。status/start/stop/uninstall 可用，没有 restart。休眠时不运行。

## 4. Agent 与 Obsidian 插件

按 [Agent 接入](AGENT.md) 注册 MCP。只用 MCP 可先不装插件；插件提供搜索面板与精确来源跳转。

```sh
cd obsidian-plugin
npm ci
npm test
npm run build
```

把生成的 `main.js`、`manifest.json`、`styles.css` 放到目标 Vault 的 `.obsidian/plugins/personal-memory-bridge/`，在 Obsidian 社区插件设置启用“我的资料”。已有同名插件先备份对应文件。设置中的端口与服务一致，插件核对 Vault 身份。

## 5. 整理规则与提示词

新库可以采用 `templates/vault/` 的规则。已有库先比较合并 `AGENTS.md` 与导航规则，不整目录覆盖。它们只提供整理方法，不创建/迁移个人笔记。

把 `personal-memory/prompts/vault-startup.txt` 填入 Claudian 公开“自定义系统提示词”设置；重新打开设置核对保存，再开新对话验证。其他 MCP 客户端可在自己的项目指令入口采用同等规则。MCP 初始化自动加载 `prompts/retrieval-tools.md`。

Skill 安装：将整个 `skills/obsidian-knowledge-system/` 复制到 `~/.codex/skills/`；若同名目录已存在，先比较。不要只复制 SKILL.md 而漏掉 references。
