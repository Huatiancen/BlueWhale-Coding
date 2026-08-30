from bluewhale_agent.evals.models import EvalAttempt, EvalReport


def test_eval_report_computes_rates_and_failure_categories() -> None:
    report = EvalReport(
        suite="mini",
        model="deepseek-chat",
        attempts=(
            EvalAttempt(
                case_id="a",
                completed=True,
                verified=True,
                repair_attempts=0,
                duration_ms=120,
                failure_types=(),
            ),
            EvalAttempt(
                case_id="b",
                completed=True,
                verified=False,
                repair_attempts=2,
                duration_ms=240,
                failure_types=("false_completion",),
            ),
        ),
    )

    assert report.completion_rate == 1.0
    assert report.verification_rate == 0.5
    assert report.average_repair_attempts == 1.0
    assert report.average_duration_ms == 180
    assert "false_completion" in report.render_markdown()
