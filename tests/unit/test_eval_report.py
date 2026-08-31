from bluewhale_agent.evals.models import EvalAttempt, EvalReport


def test_eval_report_computes_rates_and_failure_categories() -> None:
    report = EvalReport(
        suite="mini",
        model="deepseek-chat",
        attempts=(
            EvalAttempt(
                case_id="a",
                attempt_index=1,
                completed=True,
                public_verification=True,
                hidden_verification=True,
                repair_attempts=0,
                duration_ms=120,
                changed_paths=("calculator.py",),
                trajectory_path="a/1/trajectory.jsonl",
                diff_path="a/1/changes.diff",
                failure_types=(),
            ),
            EvalAttempt(
                case_id="b",
                attempt_index=1,
                completed=True,
                public_verification=False,
                hidden_verification=False,
                repair_attempts=2,
                duration_ms=240,
                failure_types=("false_completion",),
            ),
        ),
    )

    assert report.completion_rate == 1.0
    assert report.public_verification_rate == 0.5
    assert report.verification_rate == 0.5
    assert report.average_repair_attempts == 1.0
    assert report.average_duration_ms == 180
    assert "公开验证通过率：50.0%" in report.render_markdown()
    assert "a/1/changes.diff" in report.render_markdown()
    assert "false_completion" in report.render_markdown()
