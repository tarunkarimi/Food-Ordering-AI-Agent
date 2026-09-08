"""Executable deterministic evaluation harness."""

from src.evaluation.golden_dataset import load_golden_cases
from src.evaluation.models import AgentEvaluationTrace
from src.evaluation.runner import (
    evaluate_dataset,
    summarize_results,
)


def run_evaluation(
    traces: dict[str, AgentEvaluationTrace],
) -> dict[str, object]:
    """Evaluate supplied agent traces against the golden dataset."""

    cases = load_golden_cases()
    results = evaluate_dataset(
        cases,
        traces,
    )
    summary = summarize_results(results)

    return {
        "summary": summary,
        "results": results,
    }


def format_evaluation_report(
    traces: dict[str, AgentEvaluationTrace],
) -> str:
    """Create a compact human-readable evaluation report."""

    report = run_evaluation(traces)
    summary = report["summary"]

    assert hasattr(summary, "total_cases")

    lines = [
        "AI Agent Evaluation Report",
        "==========================",
        f"Total cases: {summary.total_cases}",
        f"Passed: {summary.passed_cases}",
        f"Failed: {summary.failed_cases}",
        f"Pass rate: {summary.pass_rate:.1%}",
        f"Average score: {summary.average_score:.1%}",
        f"Intent accuracy: {summary.intent_accuracy:.1%}",
        (
            "Tool-selection accuracy: "
            f"{summary.tool_selection_accuracy:.1%}"
        ),
        (
            "Response-quality rate: "
            f"{summary.response_quality_rate:.1%}"
        ),
        (
            "Safety pass rate: "
            f"{summary.safety_pass_rate:.1%}"
        ),
        (
            "Mutation correctness: "
            f"{summary.mutation_correctness_rate:.1%}"
        ),
        (
            "Personalization accuracy: "
            f"{summary.personalization_accuracy:.1%}"
        ),
    ]

    failed_results = [
        result
        for result in report["results"]
        if not result.passed
    ]

    if failed_results:
        lines.append("")
        lines.append("Failures:")

        for result in failed_results:
            lines.append(
                f"- {result.case_id}: "
                + "; ".join(result.failures)
            )

    return "\n".join(lines)
