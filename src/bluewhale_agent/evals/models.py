"""Validated evaluation suite and report contracts."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class EvalCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    language: str = Field(default="python", pattern=r"^(python|javascript|c_cpp)$")
    task: str = Field(min_length=1)
    workspace: str = Field(min_length=1)
    hidden_test: str = Field(min_length=1)
    expected_paths: tuple[str, ...] = ()


class EvalSuite(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    cases: tuple[EvalCase, ...] = Field(min_length=1)

    @classmethod
    def load(cls, path: Path) -> EvalSuite:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class EvalAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    attempt_index: int = Field(default=1, ge=1)
    completed: bool
    public_verification: bool = False
    hidden_verification: bool = False
    repair_attempts: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    changed_paths: tuple[str, ...] = ()
    trajectory_path: str | None = None
    diff_path: str | None = None
    failure_types: tuple[str, ...] = ()


class EvalReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    suite: str
    model: str
    attempts: tuple[EvalAttempt, ...]

    @property
    def completion_rate(self) -> float:
        return self._rate(sum(item.completed for item in self.attempts))

    @property
    def public_verification_rate(self) -> float:
        return self._rate(sum(item.public_verification for item in self.attempts))

    @property
    def hidden_verification_rate(self) -> float:
        return self._rate(sum(item.hidden_verification for item in self.attempts))

    @property
    def verification_rate(self) -> float:
        """Backward-compatible alias for the hidden verification rate."""

        return self.hidden_verification_rate

    @property
    def average_repair_attempts(self) -> float:
        return self._average(item.repair_attempts for item in self.attempts)

    @property
    def average_duration_ms(self) -> int:
        return round(self._average(item.duration_ms for item in self.attempts))

    def render_markdown(self) -> str:
        failures = Counter(
            failure
            for attempt in self.attempts
            for failure in attempt.failure_types
        )
        lines = [
            f"# BlueWhale 评测报告：{self.suite}",
            "",
            f"- 模型：{self.model}",
            f"- 运行次数：{len(self.attempts)}",
            f"- 完成率：{self.completion_rate:.1%}",
            f"- 公开验证通过率：{self.public_verification_rate:.1%}",
            f"- 隐藏验证通过率：{self.hidden_verification_rate:.1%}",
            f"- 平均修复轮数：{self.average_repair_attempts:.2f}",
            f"- 平均运行时间：{self.average_duration_ms / 1000:.2f} 秒",
            "",
            "## 失败类型",
        ]
        if failures:
            lines.extend(f"- {name}: {count}" for name, count in sorted(failures.items()))
        else:
            lines.append("- 无")
        lines.extend(
            (
                "",
                "## 明细",
                "",
                "| 任务 | 次数 | 完成 | 公开验证 | 隐藏验证 | 修复轮数 | 用时(ms) | 变更 | 产物 |",
                "|---|---:|---:|---:|---:|---:|---:|---|---|",
            )
        )
        lines.extend(
            f"| {item.case_id} | {item.attempt_index} | "
            f"{'是' if item.completed else '否'} | "
            f"{'通过' if item.public_verification else '未通过'} | "
            f"{'通过' if item.hidden_verification else '失败'} | "
            f"{item.repair_attempts} | {item.duration_ms} | "
            f"{', '.join(item.changed_paths) or '-'} | "
            f"{item.diff_path or item.trajectory_path or '-'} |"
            for item in self.attempts
        )
        return "\n".join(lines) + "\n"

    def write(self, directory: Path) -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / "report.json"
        markdown_path = directory / "report.md"
        json_path.write_text(
            json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        markdown_path.write_text(self.render_markdown(), encoding="utf-8")
        return json_path, markdown_path

    def _rate(self, count: int) -> float:
        return count / len(self.attempts) if self.attempts else 0.0

    @staticmethod
    def _average(values: Iterable[int]) -> float:
        materialized = list(values)
        return sum(materialized) / len(materialized) if materialized else 0.0
