BlueWhale Coding Agent

仓库：https://github.com/Huatiancen/BlueWhale-Coding

BlueWhale 是由 DeepSeek 驱动的本地编程智能体。模型通过 Tool Calling 生成操作，本地 Runtime 负责执行、权限与验证。未使用 Agent 框架或服务端代码、文件工具。

技术栈：Python 3.12、FastAPI、Uvicorn、Pydantic、DeepSeek API；原生 HTML/CSS/JavaScript、SSE；macOS 使用 pywebview、keyring；测试使用 pytest、Node Test Runner、Ruff、Mypy。

安装：
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[desktop,dev]'
cp .env.example .env

在 .env 配置 DEEPSEEK_API_KEY。桌面端运行 bluewhale desktop；Web 端运行 bluewhale serve --workspace /项目绝对路径。

核心亮点：
1. 自研执行循环：自行实现模型响应解析、工具注册与执行、上下文压缩、错误恢复、步骤预算和稳定终止条件。
2. 证据驱动：模型的文字声明不直接视为完成；文件差异、命令结果和测试结果会进入独立证据账本。
3. 验证修复闭环：自动发现项目验证命令，失败后进行有限次修复，并通过错误指纹识别无进展循环。
4. 本地安全边界：文件访问被限制在选定工作区；高风险操作请求单次审批，无法安全限定目标的操作会被拒绝。
5. 渐进式 Skills：任务开始时只提供 Skill 元数据，匹配后再按需加载完整工作流；Skill 不能绕过权限和沙箱规则。
6. 完整 GUI：支持流式回答、分轮工作过程、本地历史续聊、Markdown、语法高亮 Diff、文件变更汇总和冲突感知撤销。
7. 可恢复轨迹：运行事件追加保存为 JSONL，支持中断恢复、断线回放和脱敏诊断导出。
8. 可重复评测：内置 Python、JavaScript、C 和 C++ 修复任务，记录公开验证、隐藏验证、越界操作和无关文件修改。

桌面历史位于 ~/Library/Application Support/BlueWhale；项目数据与 Skills 可位于工作区 .bluewhale。执行与持久化均在本机；DeepSeek API 仅接收任务所需上下文和代码片段。

验证：python -m pytest -q、python -m ruff check src tests、python -m mypy src。
