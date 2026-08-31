BlueWhale Coding Agent

公开仓库地址：https://github.com/Huatiancen/BlueWhale-Coding

BlueWhale 是一个由 DeepSeek 驱动、完全在本地执行的编程智能体。模型负责理解目标并生成结构化工具调用，本地 Runtime 负责读取与修改文件、执行命令、管理上下文、校验权限、运行测试和判断任务是否真正完成。项目未使用第三方 Agent 框架，也未依赖服务端托管的代码执行或文件工具。

运行环境：Python 3.12 及以上。

安装：
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[desktop,dev]'
cp .env.example .env

在 .env 中填写自己的 DEEPSEEK_API_KEY。可通过 BLUEWHALE_MODEL 修改模型，默认值为 deepseek-v4-flash。真实密钥不得提交到仓库。

启动 macOS GUI：
bluewhale desktop

也可以启动本地 Web GUI：
bluewhale serve --workspace /需要操作的项目绝对路径

随后访问：http://127.0.0.1:8000

核心亮点：
1. 自研执行循环：自行实现模型响应解析、工具注册与执行、上下文压缩、错误恢复、步骤预算和稳定终止条件。
2. 证据驱动：模型的文字声明不直接视为完成；文件差异、命令结果和测试结果会进入独立证据账本。
3. 验证修复闭环：自动发现项目验证命令，失败后进行有限次修复，并通过错误指纹识别无进展循环。
4. 本地安全边界：文件访问被限制在选定工作区；高风险操作请求单次审批，无法安全限定目标的操作会被拒绝。
5. 渐进式 Skills：任务开始时只提供 Skill 元数据，匹配后再按需加载完整工作流；Skill 不能绕过权限和沙箱规则。
6. 完整 GUI：支持流式回答、分轮工作过程、本地历史续聊、Markdown、语法高亮 Diff、文件变更汇总和冲突感知撤销。
7. 可恢复轨迹：运行事件追加保存为 JSONL，支持中断恢复、断线回放和脱敏诊断导出。
8. 可重复评测：内置 Python、JavaScript、C 和 C++ 修复任务，记录公开验证、隐藏验证、越界操作和无关文件修改。

一次完整任务从用户选择工作区并描述目标开始。BlueWhale 先解析项目结构和局部规则，再让模型生成结构化 Action。每个 Action 都要经过参数校验、工作区边界检查和权限判定，才能交给本地工具执行。执行结果会作为 Observation 返回后续轮次，并同步进入轨迹、证据和 GUI 工作过程。涉及文件修改时，系统还会独立生成 Diff，并在任务结束前执行可用的测试、类型检查或构建命令。

项目按职责划分为模型适配、执行循环、本地工具、权限策略、验证门禁、证据账本、轨迹存储和用户界面等模块。各模块通过稳定的领域对象传递数据，便于替换模型、扩展工具和独立测试。离线测试覆盖文件工具、命令策略、历史恢复、流式事件、审批、撤销、Skills 和输入法等关键路径。内置评测完成 45 次真实模型运行，完成率为 97.8%，隐藏验证通过率为 95.6%。

本地数据保存在工作区的 .bluewhale 目录，不会上传历史对话或项目源码。API Key 可由 macOS 钥匙串保存，事件和诊断信息写入前会进行脱敏。

演示项目：demo/bluewhale-repair-demo
推荐演示指令见该目录中的“验证指令.md”。

离线验证：
python -m pytest -q
python -m ruff check src tests
python -m mypy src

真实 DeepSeek 契约测试默认跳过。只有显式设置 BLUEWHALE_RUN_LIVE_TESTS=1 并提供 API Key 时才会调用网络。
