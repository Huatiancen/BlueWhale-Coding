BlueWhale Coding Agent

仓库：https://github.com/Huatiancen/BlueWhale-Coding

项目简介

BlueWhale 是由 DeepSeek 驱动、面向 macOS 的本地编程智能体。用户选择工作区并描述任务后，模型通过原生 Tool Calling 规划操作，本地 Runtime 负责读取与修改文件、执行命令、权限判定、结果验证和过程持久化。项目未使用任何 Agent 框架，也未依赖服务端托管的代码执行或文件工具，核心调度、安全和恢复逻辑均自行实现。

技术栈

后端使用 Python 3.12、FastAPI、Uvicorn、Pydantic 与 DeepSeek API；界面使用原生 HTML、CSS、JavaScript 和 SSE；macOS 桌面端使用 pywebview、keyring 与 Seatbelt；质量检查使用 pytest、Node Test Runner、Ruff 和 Mypy。

安装与运行

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[desktop,dev]'
cp .env.example .env

在 .env 中配置 DEEPSEEK_API_KEY，运行 bluewhale desktop 启动桌面端；也可运行 bluewhale serve --workspace /项目绝对路径 启动本地 Web 服务。

工作方式

每轮任务会依次完成上下文构建、模型决策、工具执行、结果观察与验证。模型只能调用 BlueWhale 注册的本地工具，不能直接操作系统。默认不限制模型调用次数和总运行时长，每完成二十次调用会进行一次非阻断进度检查；用户仍可随时停止任务，显式资源限制和不可恢复错误也会安全结束运行。

核心亮点

1. 自研执行循环：自行实现流式响应解析、工具注册与调度、上下文压缩、协议修复和稳定终止，不把关键能力交给第三方 Agent 框架。
2. 证据驱动：模型的文字声明不直接视为完成，文件差异、命令输出、测试结果和计划状态会进入独立证据账本，最终结论必须与本地证据一致。
3. 验证修复闭环：自动发现项目验证命令，测试失败后允许模型继续诊断和修复，并通过错误指纹识别重复失败，避免在无进展路径上无限循环。
4. 权限与沙箱分层：文件访问被限制在用户选择的工作区；普通读写可自动执行，高风险操作请求单次审批，命令在 macOS Seatbelt 中隔离运行。
5. 渐进式 Skills：启动时只向模型提供 Skill 名称、描述和作用域，任务匹配后再加载完整说明与资源，兼顾上下文成本、项目规范和安全边界。
6. 完整桌面 GUI：支持流式回答、思考与工具过程分离、Markdown、语法高亮 Diff、变更汇总和面板缩放；可撤销整轮或单个文件，并通过内容指纹避免覆盖后续编辑。
7. 本地历史与恢复：会话事件以追加式 JSONL 保存，支持历史续聊、中断恢复、断线回放、未配对工具调用修复和脱敏诊断导出。
8. 可重复评测：内置 Python、JavaScript、C 和 C++ 修复任务，同时记录公开验证、隐藏验证、越界操作和无关文件修改，便于稳定比较真实项目能力。

本地数据与隐私

桌面历史位于 ~/Library/Application Support/BlueWhale，工作区授权、事件轨迹、命令日志和变更快照均保存在本机。DeepSeek API 只接收完成当前任务所需的提示、代码片段和工具观察，不会通过 BlueWhale 上传完整项目或历史数据库。

验证命令

python -m pytest -q
python -m ruff check src tests
python -m mypy src
