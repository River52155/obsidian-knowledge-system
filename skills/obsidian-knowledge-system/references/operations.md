# 运行、迁移与验收

## 先盘点

确认项目包含 memory_search.py、mcp_bridge.py、prompts/ 与 obsidian-plugin/。检查 Git 未提交内容、现有进程/端口、Vault 的 AGENTS.md、真实服务 health 和索引状态。生产运行时不要再起第二个实例；不要把历史 README 的模型/测试计数当当前配置。

三处提示源：prompts/vault-startup.txt（Claudian 公开自定义系统提示）、prompts/research-query-rules.md（Vault 导航/资料查询规则.md）、prompts/retrieval-tools.md（新 MCP 连接的初始化说明）。修改后逐处部署和读回；旧连接/长会话可能保留旧上下文。公开设置显示新值、重开后保存、新聊天实际使用是三个不同检查。

## 新机器迁移

当前源码仍有本机默认路径、固定允许目录与 macOS launchd 约定，不能宣称跨平台一键安装。

1. 按目标 Vault 审查 memory_search.py 的 DEFAULT_VAULT、ROOTS、BLOCKED_DIRS；保持明确允许范围，不能默认扫描全库。研究集合配置单独重建为已审核相对路径，不复制个人集合数据。
2. 项目目录建立 Python 3.11 虚拟环境，按 requirements.lock.txt 安装；按 embedding-model.json 获取固定版本本地模型。可用 `uv venv .venv --python python3.11`、`uv pip install --python .venv/bin/python -r requirements.lock.txt`、`.venv/bin/python semantic_search.py download`。
3. 仅新安装/离线重建时：`.venv/bin/python memory_search.py build --vault '<已确认的Vault绝对路径>'`，再 `.venv/bin/python semantic_search.py build`。运行中的更新使用服务更新流程，不直接覆盖 baseline。
4. `memory_search.py serve --port <端口>` 从数据库读取 Vault 元数据；没有 serve --vault 参数。先验证独立端口服务，再决定托管。service_control.py 目前固定8767与用户级标签，迁移时先审查，不能无条件覆盖现有 LaunchAgent。
5. 通过客户端公开 MCP 配置注册 `<项目>/.venv/bin/python <项目>/mcp_bridge.py --vault <Vault> --port <端口>`。模型认证沿用目标客户端，不复制其他人的账户配置。
6. 插件在 obsidian-plugin/ 执行 `npm ci`、`npm test`、`npm run build`；在用户授权范围安装到目标 Vault 独立插件目录。Claudian 作为外部依赖，不打包或修改其 bundle。
7. 按当前规则入口放置/更新最小必要文件；已有规则先比较合并，不覆盖目标 Vault 权限和后续改动。通过公开设置修改启动提示，并读回验证。

## 更新与恢复

运行时定期检查允许文件；变化后复用未变向量输入，构建并验证一对新文字/向量索引，再原子发布。刷新请求成功不等于更新完成；等成功状态与当前版本，再检索新文字。失败保留旧版，新内容可能未生效。历史 last_failure 与当前 active_error 分开解释。

来源文件、data/generations、active-index.json 与模型配置各司其职。备份恢复必须匹配代码、配置和索引版本；不能只退数据库。旧版本清理先停服务并预览，按实际 generation_store.py CLI 执行，不手工广泛删除。service_control.py 有 install/start/stop/status/uninstall，没有 restart。

## 验收

- 涉及检索代码：相关 Python 测试，必要时 `python -m unittest discover -v`。
- 涉及插件：npm test 与 build；原生点击另外验证。
- 涉及提示：现有 MCP 加载测试、真实新连接 instructions 核对；固定合成模型对照按已授权预算执行。
- 更新：临时库新增、修改、删除、重命名，确认成功发布、新内容可查、旧引用失效、失败保留旧版。
- 时间线：跨月/文件名不含目标月份、未读页、歧义日期；知识问题：教程不等于实践，计划不等于完成。
- 来源定位：长行、emoji、未保存缓冲区；程序定位通过不等于原生点击通过。

报告代码测试、模型输出和 UI 验证各自结果。附件正文解析、模型无依据扩写、原生回答语义硬拦截仍不可假定已解决。回滚前保存对应文件版本与 SHA，避免复制完整配置或凭据。
