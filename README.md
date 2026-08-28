# BlueWhale Coding Agent

BlueWhale 是一个由 DeepSeek 驱动、证据优先（evidence-driven）的本地 Coding Agent。它不依赖 LangChain、LlamaIndex、OpenAI Agents SDK、AutoGen、CrewAI 等 Agent 框架，也不使用服务端托管的代码执行或文件工具；执行循环、权限策略、文件工具、验证门禁、轨迹存储和 Web GUI 均在仓库内自行实现。

项目面向“给定目标—检查代码—修改文件—运行验证—失败后修复—展示证据”的完整开发闭环。模型提出 Action，本地 Runtime 产生 Observation，最终结论必须由本地 diff、命令输出或测试结果支撑。

## 核心亮点

- **可回放执行轨迹**：每个事件按序写入 JSONL，SSE 断线后可通过 `Last-Event-ID` 继续回放。
- **证据账本**：模型文本不等于事实；文件变更、搜索结果和测试结果被转换为独立 Evidence。
- **验证—修复闭环**：自动发现项目声明的测试、类型检查和构建命令；失败后有限次请求模型修复，并检测无进展循环。
- **本地安全边界**：所有路径限制在选定工作区内，危险命令直接拒绝，高风险操作通过 GUI 单次审批。
- **实时 Web GUI**：浏览器中查看会话、模型/工具事件、diff、验证证据和审批状态，无需 TUI。

## 架构

```mermaid
flowchart LR
    GUI[Web GUI] -->|REST / SSE| Sessions[Session Manager]
    Sessions --> Loop[Agent Loop]
    Loop --> Provider[DeepSeek Provider]
    Loop --> Registry[Local Tool Registry]
    Registry --> Policy[Permission Policy]
    Registry --> Workspace[Workspace Files / Commands]
    Loop --> Gate[Verification Gate]
    Loop --> Ledger[Evidence Ledger]
    Loop --> Trajectory[JSONL Trajectory]
    Trajectory -->|replay| GUI
```

主要分层：

- `providers/`：将 OpenAI 兼容的 DeepSeek Chat Completions 转换为内部 `ModelResponse`。
- `agent/`：维护消息历史、步骤预算、终止条件和工具执行循环。
- `tools/`、`runtime/`：参数校验、路径约束、原子文件修改、命令执行和权限判定。
- `verification/`：发现验证命令，归一化结果，控制有限修复和无进展停止。
- `evidence/`、`trajectory/`：生成可核验证据，并持久化可回放事件。
- `web/`：管理后台任务、审批 Future、REST/SSE API 和原生 HTML/CSS/JavaScript GUI。

## 环境要求与安装

- Python 3.12 或更高版本
- 一个 DeepSeek API Key

```bash
git clone https://github.com/Huatiancen/BlueWhale-Coding.git
cd BlueWhale-Coding
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

Windows PowerShell 激活命令为：

```powershell
.venv\Scripts\Activate.ps1
```

## 配置 DeepSeek

编辑 `.env`：

```dotenv
DEEPSEEK_API_KEY=在此填写你自己的密钥
BLUEWHALE_MODEL=deepseek-v4-pro
BLUEWHALE_BASE_URL=https://api.deepseek.com
```

配置由 `pydantic-settings` 读取。API Key 使用 `SecretStr` 保存，不会被写入请求正文、事件轨迹或错误信息。`.env` 已被 Git 忽略，请勿提交真实凭据。

## 启动 Web GUI

```bash
bluewhale serve --workspace /absolute/path/to/your/project
```

默认仅监听本机 `127.0.0.1:8000`。浏览器打开：

```text
http://127.0.0.1:8000
```

也可以指定端口：

```bash
bluewhale serve --workspace . --host 127.0.0.1 --port 8765
```

在 GUI 中输入开发目标后，BlueWhale 会实时展示 PLAN、MODEL、TOOL、EDIT、TEST、ERROR 和 DONE 事件。覆盖文件、安装依赖、网络请求或 Git 写操作等 ASK 类行为必须由用户批准一次；拒绝、超时或停止都不会执行该操作。

## 安全边界

- 文件访问必须位于 `--workspace` 指定目录内，拒绝路径穿越和越界符号链接。
- `.git`、`.env*` 和 `.bluewhale` 被视为受保护路径。
- `rm`、`sudo`、`git reset` 等危险或破坏性命令直接拒绝。
- 已知只读工具和常见测试命令可自动执行；未知命令默认请求审批。
- 审批仅对当前 Action 生效，不能重复使用；默认 60 秒超时并按拒绝处理。
- 命令具有超时限制，Agent 具有步骤数、修复次数和总运行时间预算。

## 本地数据

每次运行会在目标工作区创建：

```text
.bluewhale/runs/<run-id>/events.jsonl
```

轨迹是追加写入的结构化事件，用于 GUI 回放和审计。写入前会递归脱敏常见密钥、令牌和认证字段。该目录已在本仓库的 `.gitignore` 中忽略；对其他目标项目使用时，也建议将 `.bluewhale/` 加入其忽略规则。

## 测试

运行全部离线测试：

```bash
python -m pytest -q
python -m ruff check src tests
python -m mypy src
```

`tests/fixtures/sample_project` 是故意包含除零错误的演示素材，因此不会被常规测试递归收集。集成测试会将它复制到临时目录，并覆盖“首次修复通过”和“验证失败后自动修复”两条工作流。

真实 DeepSeek 契约测试默认跳过，不会访问网络或产生费用。只有同时显式设置开关和密钥时才会运行：

```bash
BLUEWHALE_RUN_LIVE_TESTS=1 \
DEEPSEEK_API_KEY=你的密钥 \
python -m pytest tests/integration/test_deepseek_contract.py -q
```

这些测试验证普通回答、原生 tool calling，以及 thinking tool call 后续轮次对 `reasoning_content` 的回传。

## 终止结果

BlueWhale 使用稳定的停止原因区分完成、部分验证、用户停止、步骤/时间限制、权限拒绝、API 错误、协议错误、工具错误、验证失败和无进展。GUI 的“已完成”并不隐含“验证通过”，应同时查看 `verified` 状态和 Evidence 面板。

## License

本项目使用仓库内 [LICENSE](LICENSE) 所述许可证。
