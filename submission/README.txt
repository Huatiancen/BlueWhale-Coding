BlueWhale Coding Agent

公开仓库地址（提交前请设为 Public）：https://github.com/Huatiancen/BlueWhale-Coding

运行环境：Python 3.12 及以上。进入仓库后执行：
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env

在 .env 中填写自己的 DEEPSEEK_API_KEY，可按需修改 BLUEWHALE_MODEL，默认使用 deepseek-v4-flash。请勿提交真实密钥。

启动命令：
bluewhale serve --workspace /需要操作的项目绝对路径

浏览器地址：http://127.0.0.1:8000

四个亮点：
1. 自研 Agent Harness：未使用任何 Agent 框架或服务端代码执行工具，模型只产生结构化 Action，本地 Runtime 负责校验和执行。
2. Evidence Ledger：模型陈述不直接视为完成，文件 diff、命令结果和测试结果被记录为可核验证据。
3. Verification Gate：自动运行项目声明的验证命令；失败后有限次修复，并通过错误指纹阻止无进展循环。
4. 安全实时 GUI：SSE 展示完整轨迹，高风险操作单次审批；越界路径和危险命令直接拒绝，事件持久化后可断线回放。

离线验证：python -m pytest -q。真实 DeepSeek 契约测试默认跳过，只有显式设置 BLUEWHALE_RUN_LIVE_TESTS 为 1 且提供密钥时才运行。
