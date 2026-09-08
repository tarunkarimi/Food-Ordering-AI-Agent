"""Regression thresholds for AI-agent evaluation quality."""

from src.evaluation.golden_dataset import load_golden_cases
from src.evaluation.models import AgentEvaluationTrace
from src.evaluation.runner import (
    assert_evaluation_thresholds,
    evaluate_dataset,
    summarize_results,
)


def _build_baseline_traces():
    cases = load_golden_cases()

    return {
        case.case_id: AgentEvaluationTrace(
            response="Evaluation response.",
            predicted_intent=case.expected_intent,
            tools_called=case.expected_tools,
            cart_mutated=case.expected_cart_mutation,
            order_mutated=case.expected_order_mutation,
            authenticated=case.authenticated,
            personalization_used=case.requires_personalization,
        )
        for case in cases
    }


def test_ai_agent_regression_thresholds():
    """Golden baseline must satisfy all mandatory quality thresholds."""

    cases = load_golden_cases()
    traces = _build_baseline_traces()

    results = evaluate_dataset(
        cases,
        traces,
    )

    summary = summarize_results(results)

    assert_evaluation_thresholds(
        summary,
        minimum_pass_rate=1.0,
        minimum_intent_accuracy=1.0,
        minimum_tool_selection_accuracy=1.0,
        minimum_safety_pass_rate=1.0,
        minimum_mutation_correctness_rate=1.0,
    )
