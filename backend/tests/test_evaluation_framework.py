"""Tests for the deterministic AI-agent evaluation framework."""

from src.evaluation.golden_dataset import load_golden_cases
from src.evaluation.models import AgentEvaluationTrace
from src.evaluation.runner import (
    assert_evaluation_thresholds,
    evaluate_case,
    evaluate_dataset,
    summarize_results,
)
from src.evaluation.runner_cli import (
    format_evaluation_report,
)


def _case(case_id: str):
    return next(
        case
        for case in load_golden_cases()
        if case.case_id == case_id
    )


def test_golden_dataset_loads_expected_cases():
    cases = load_golden_cases()

    assert len(cases) == 20

    case_ids = {case.case_id for case in cases}

    assert "menu_001" in case_ids
    assert "cart_001" in case_ids
    assert "history_001" in case_ids
    assert "preference_001" in case_ids
    assert "recommendation_002" in case_ids
    assert "reorder_001" in case_ids
    assert "security_001" in case_ids


def test_golden_dataset_has_unique_case_ids():
    cases = load_golden_cases()

    case_ids = [case.case_id for case in cases]

    assert len(case_ids) == len(set(case_ids))


def test_correct_intent_passes():
    case = _case("menu_001")

    trace = AgentEvaluationTrace(
        response="Here is the menu.",
        predicted_intent="menu_browse",
        tools_called=("get_menu",),
    )

    result = evaluate_case(case, trace)

    assert result.passed is True
    assert result.checks["intent"] is True


def test_wrong_intent_fails():
    case = _case("menu_001")

    trace = AgentEvaluationTrace(
        response="Here is the menu.",
        predicted_intent="cart_add",
        tools_called=("get_menu",),
    )

    result = evaluate_case(case, trace)

    assert result.passed is False
    assert result.checks["intent"] is False


def test_missing_expected_tool_fails():
    case = _case("menu_001")

    trace = AgentEvaluationTrace(
        response="Here is the menu.",
        predicted_intent="menu_browse",
        tools_called=(),
    )

    result = evaluate_case(case, trace)

    assert result.passed is False
    assert (
        "Expected tools were not all called: get_menu"
        in result.failures
    )


def test_forbidden_tool_fails():
    case = _case("recommendation_002")

    trace = AgentEvaluationTrace(
        response="I recommend something.",
        predicted_intent="advanced_recommendation",
        tools_called=(
            "advanced_recommend_food",
            "add_to_cart",
        ),
        cart_mutated=True,
        order_mutated=False,
        personalization_used=True,
    )

    result = evaluate_case(case, trace)

    assert result.passed is False
    assert any(
        "Forbidden tools were called" in failure
        for failure in result.failures
    )


def test_response_quality_required_terms():
    case = _case("menu_001")

    case = type(case)(
        **{
            **case.__dict__,
            "required_response_terms": ("menu",),
        }
    )

    trace = AgentEvaluationTrace(
        response="Here is the menu.",
        predicted_intent="menu_browse",
        tools_called=("get_menu",),
    )

    result = evaluate_case(case, trace)

    assert result.checks["required_response_terms"] is True


def test_response_quality_missing_terms_fails():
    case = _case("menu_001")

    case = type(case)(
        **{
            **case.__dict__,
            "required_response_terms": ("restaurant menu",),
        }
    )

    trace = AgentEvaluationTrace(
        response="Sure, I can help.",
        predicted_intent="menu_browse",
        tools_called=("get_menu",),
    )

    result = evaluate_case(case, trace)

    assert result.passed is False
    assert result.checks["required_response_terms"] is False


def test_forbidden_response_content_fails():
    case = _case("security_001")

    trace = AgentEvaluationTrace(
        response="Your password is secret123.",
        predicted_intent="security_refusal",
        tools_called=(),
    )

    result = evaluate_case(case, trace)

    assert result.passed is False
    assert result.checks["forbidden_response_terms"] is False
    assert result.checks["safety"] is False


def test_recommendation_without_cart_mutation_passes():
    case = _case("recommendation_004")

    trace = AgentEvaluationTrace(
        response="I found a suitable recommendation.",
        predicted_intent="advanced_recommendation",
        tools_called=("advanced_recommend_food",),
        cart_mutated=False,
        order_mutated=False,
        personalization_used=True,
    )

    result = evaluate_case(case, trace)

    assert result.passed is True
    assert result.checks["cart_mutation"] is True
    assert result.checks["order_mutation"] is True


def test_unexpected_cart_mutation_fails():
    case = _case("recommendation_004")

    trace = AgentEvaluationTrace(
        response="I found a recommendation.",
        predicted_intent="advanced_recommendation",
        tools_called=("advanced_recommend_food",),
        cart_mutated=True,
        order_mutated=False,
        personalization_used=True,
    )

    result = evaluate_case(case, trace)

    assert result.passed is False
    assert result.checks["cart_mutation"] is False


def test_personalization_is_required():
    case = _case("history_002")

    trace = AgentEvaluationTrace(
        response="You usually order biryani.",
        predicted_intent="personalization",
        tools_called=("get_my_food_preferences",),
        personalization_used=False,
    )

    result = evaluate_case(case, trace)

    assert result.passed is False
    assert result.checks["personalization_used"] is False


def test_personalization_usage_passes():
    case = _case("history_002")

    trace = AgentEvaluationTrace(
        response="You usually order biryani.",
        predicted_intent="personalization",
        tools_called=("get_my_food_preferences",),
        personalization_used=True,
    )

    result = evaluate_case(case, trace)

    assert result.passed is True


def test_security_authentication_mismatch_fails():
    case = _case("security_001")

    trace = AgentEvaluationTrace(
        response="I can't provide passwords.",
        predicted_intent="security_refusal",
        authenticated=True,
    )

    # Security cases explicitly default to authenticated=True
    # because the case represents an authenticated user asking
    # for sensitive information.
    result = evaluate_case(case, trace)

    assert result.checks["safety"] is True


def test_dataset_evaluation_and_summary():
    cases = load_golden_cases()

    traces = {
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

    results = evaluate_dataset(
        cases,
        traces,
    )

    summary = summarize_results(results)

    assert len(results) == 20
    assert summary.total_cases == 20
    assert summary.passed_cases == 20
    assert summary.failed_cases == 0
    assert summary.pass_rate == 1.0
    assert summary.intent_accuracy == 1.0
    assert summary.tool_selection_accuracy == 1.0
    assert summary.safety_pass_rate == 1.0
    assert summary.mutation_correctness_rate == 1.0


def test_thresholds_pass_for_perfect_evaluation():
    cases = load_golden_cases()

    traces = {
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

    summary = summarize_results(
        evaluate_dataset(cases, traces)
    )

    assert_evaluation_thresholds(summary)


def test_thresholds_fail_when_quality_drops():
    cases = load_golden_cases()

    traces = {
        case.case_id: AgentEvaluationTrace(
            response="Evaluation response.",
            predicted_intent=(
                "wrong_intent"
                if case.case_id == "menu_001"
                else case.expected_intent
            ),
            tools_called=case.expected_tools,
            cart_mutated=case.expected_cart_mutation,
            order_mutated=case.expected_order_mutation,
            authenticated=case.authenticated,
            personalization_used=case.requires_personalization,
        )
        for case in cases
    }

    summary = summarize_results(
        evaluate_dataset(cases, traces)
    )

    try:
        assert_evaluation_thresholds(summary)
    except AssertionError as exc:
        assert "intent_accuracy" in str(exc)
    else:
        raise AssertionError(
            "Threshold evaluation should have failed."
        )


def test_report_contains_core_metrics():
    cases = load_golden_cases()

    traces = {
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

    report = format_evaluation_report(traces)

    assert "AI Agent Evaluation Report" in report
    assert "Total cases: 20" in report
    assert "Pass rate: 100.0%" in report
    assert "Intent accuracy: 100.0%" in report
    assert "Tool-selection accuracy: 100.0%" in report
    assert "Safety pass rate: 100.0%" in report
