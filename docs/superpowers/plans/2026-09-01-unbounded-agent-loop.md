# BlueWhale 无固定上限 Agent Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 BlueWhale 默认持续运行到模型自然完成任务，并每 20 次模型调用执行一次不增加 API 请求的进度审计。

**Architecture:** 将步数和总时长限制改为可选配置，只有显式配置时才触发原有终止逻辑。AgentLoop 在单次连续执行的第 20、40 等次模型调用完成后，将一次性系统审计指令附加到下一次正常模型请求，并用轨迹事件记录审计发生。

**Tech Stack:** Python 3.11、Pydantic、asyncio、pytest、BlueWhale 本地 TrajectoryStore。

---

### Task 1: 可选运行上限

**Files:**
- Modify: `src/bluewhale_agent/domain/models.py`
- Modify: `src/bluewhale_agent/agent/state.py`
- Modify: `src/bluewhale_agent/agent/loop.py`
- Test: `tests/unit/test_agent_state.py`
- Test: `tests/integration/test_agent_loop.py`

- [ ] **Step 1: 写默认无限与显式限制的失败测试**

```python
def test_default_limits_do_not_cap_steps_or_wall_time() -> None:
    limits = Limits()
    assert limits.max_steps is None
    assert limits.max_wall_time_seconds is None
    assert limits.progress_check_interval == 20

def test_record_step_keeps_running_without_an_explicit_limit() -> None:
    state = AgentState.start("repair bug")
    state.mark_running()
    for _ in range(25):
        state.record_step()
    assert state.status is RunStatus.RUNNING
```

- [ ] **Step 2: 运行测试并确认因默认值和可选值尚未实现而失败**

Run: `pytest tests/unit/test_agent_state.py -q`

Expected: 新增断言失败，显示默认 `max_steps` 仍为 `20`，或无限模式比较时报错。

- [ ] **Step 3: 实现可选限制并保留显式上限行为**

```python
class Limits(BaseModel):
    max_steps: int | None = Field(default=None, gt=0)
    max_wall_time_seconds: int | None = Field(default=None, gt=0)
    progress_check_interval: int = Field(default=20, gt=0)

def _guard_model_call(self) -> None:
    self._guard_runtime()
    if self._limits.max_steps is not None:
        if self._state_required().steps_taken >= self._limits.max_steps:
            raise _TerminalRun(StopReason.STEP_LIMIT)
```

`AgentState.record_step` 与 `_guard_runtime` 使用同样的 `is not None` 分支，显式正整数时继续执行原有停止逻辑。

- [ ] **Step 4: 运行单元测试确认默认无限与显式限制均通过**

Run: `pytest tests/unit/test_agent_state.py -q`

Expected: 全部通过。

### Task 2: 每 20 次无阻塞进度审计

**Files:**
- Modify: `src/bluewhale_agent/domain/events.py`
- Modify: `src/bluewhale_agent/agent/loop.py`
- Test: `tests/integration/test_agent_loop.py`

- [ ] **Step 1: 写第 21、41 次请求注入审计且不增加调用的失败测试**

```python
@pytest.mark.asyncio
async def test_default_loop_audits_every_twenty_calls_without_stopping(tmp_path: Path) -> None:
    provider = FakeModelProvider([...40 个工具响应..., response(content="完成。")])
    result = await AgentLoop(run_id="progress-audit", workspace=tmp_path, provider=provider).run("完成任务")
    assert result.stop_reason is StopReason.COMPLETED
    assert len(provider.calls) == 41
    assert "Progress checkpoint" in system_text(provider.calls[20][0])
    assert "Progress checkpoint" in system_text(provider.calls[40][0])
    assert "Progress checkpoint" not in system_text(provider.calls[19][0])
```

- [ ] **Step 2: 运行新增集成测试并确认第 20 次后仍触发 STEP_LIMIT**

Run: `pytest tests/integration/test_agent_loop.py -k 'progress_audit or default_loop' -q`

Expected: FAIL，默认循环在第 20 次停止，或请求中缺少进度审计。

- [ ] **Step 3: 增加一次性审计消息与持久化事件**

```python
class EventKind(StrEnum):
    PROGRESS_CHECKED = "progress_checked"

def _progress_check_message(self) -> Message | None:
    steps = self._state_required().steps_taken
    interval = self._limits.progress_check_interval
    if steps <= 0 or steps % interval or steps == self._last_progress_check_step:
        return None
    self._last_progress_check_step = steps
    self._emit(EventKind.PROGRESS_CHECKED, {"model_calls": steps, "interval": interval})
    return Message(role=MessageRole.SYSTEM, content=_PROGRESS_CHECK_PROMPT.format(steps=steps))
```

在 `_request_model` 构建正常请求后附加该消息。审计消息不写入对话历史，因此不污染用户回答，也不会额外调用模型；新一轮执行从零重新计数，不会被同一历史会话中上一轮的审计事件抑制。

- [ ] **Step 4: 运行进度审计集成测试**

Run: `pytest tests/integration/test_agent_loop.py -k 'progress_audit or step_limit or wall_time' -q`

Expected: 默认任务在 41 次调用后自然完成；第 21、41 次请求各含一次审计；显式步数和时长限制仍通过。

### Task 3: 回归验证与静态检查

**Files:**
- Verify: `src/bluewhale_agent/domain/models.py`
- Verify: `src/bluewhale_agent/domain/events.py`
- Verify: `src/bluewhale_agent/agent/state.py`
- Verify: `src/bluewhale_agent/agent/loop.py`
- Verify: `tests/unit/test_agent_state.py`
- Verify: `tests/integration/test_agent_loop.py`

- [ ] **Step 1: 运行相关 Python 回归测试**

Run: `pytest tests/unit/test_agent_state.py tests/integration/test_agent_loop.py -q`

Expected: 全部通过。

- [ ] **Step 2: 运行代码质量检查**

Run: `ruff check src tests`

Expected: `All checks passed!`

Run: `mypy src`

Expected: `Success: no issues found`。

- [ ] **Step 3: 运行完整测试并记录与本功能无关的既有失败**

Run: `pytest -q`

Expected: 本次相关测试全部通过；若 `demo/ExpenseFlow` 的已修改演示夹具导致既有“初始失败”测试失败，单独记录且不覆盖用户修改。

- [ ] **Step 4: 审查未提交差异**

Run: `git diff --check && git status --short`

Expected: 无空白错误；只保留本次实现、此前未提交改动和用户已有的 `demo/ExpenseFlow` 修改，不创建提交。
