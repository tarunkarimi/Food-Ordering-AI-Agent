from src.evaluation.models import EvaluationCase
from src.testing_agent.evaluation_adapter import (
    build_testing_agent_trace,
    evaluate_testing_agent_case,
)
import src.testing_agent.models as testing_models
from src.testing_agent.qa_report import build_qa_report


def _case(
    *,
    test_type="functional",
    priority="high",
    tags=("functional",),
):
    return testing_models.TestCase(
        test_case_id="TC-001",
        title="Test cart behavior",
        scenario_id="TS-001",
        test_type=test_type,
        priority=priority,
        preconditions=(),
        steps=("Execute operation.",),
        expected_result="Operation succeeds.",
        tags=tags,
    )


def test_qa_report_aggregates_test_coverage():
    scenarios = [
        testing_models.TestScenario(
            scenario_id="TS-001",
            title="Authentication",
            objective="Verify access",
            priority="critical",
            tags=("security", "authorization"),
        ),
    ]

    report = build_qa_report(
        "Authenticated users can access protected resources.",
        scenarios,
        [
            _case(
                priority="critical",
                tags=("security", "authorization"),
            ),
            _case(
                test_type="negative",
                tags=("negative", "validation"),
            ),
            _case(
                test_type="edge-case",
                tags=("edge-case", "boundary"),
            ),
        ],
    )

    assert report.scenario_count == 1
    assert report.test_case_count == 3
    assert report.critical_count == 1
    assert report.negative_count == 1
    assert report.edge_case_count == 1
    assert report.security_count == 1
    assert "security" in report.coverage_areas


def test_qa_report_identifies_security_risk():
    scenario = testing_models.TestScenario(
        scenario_id="TS-001",
        title="Authorization",
        objective="Verify ownership",
        priority="critical",
        tags=("security", "authorization"),
    )

    report = build_qa_report(
        "Authorization requirement",
        [scenario],
        [],
    )

    assert report.risks
    assert "authorization" in report.risks[0].lower()


def test_testing_agent_trace_is_evaluator_compatible():
    trace = build_testing_agent_trace(
        response="Generated functional test cases.",
        test_cases=[_case()],
        predicted_intent="test_generation",
        tools_called=("generate_ai_test_cases",),
    )

    assert trace.predicted_intent == "test_generation"
    assert trace.tools_called == ("generate_ai_test_cases",)
    assert trace.authenticated is True


def test_testing_agent_case_evaluation_uses_existing_framework():
    case = EvaluationCase(
        case_id="TEST-001",
        category="testing_agent",
        user_message="Generate test cases",
        expected_intent="test_generation",
        expected_tools=("generate_ai_test_cases",),
        authenticated=True,
    )

    trace = build_testing_agent_trace(
        response="Generated test cases.",
        test_cases=[_case()],
        predicted_intent="test_generation",
        tools_called=("generate_ai_test_cases",),
    )

    result = evaluate_testing_agent_case(case, trace)

    assert result.passed is True
    assert result.checks["intent"] is True
    assert result.checks["expected_tools_called"] is True
    assert result.checks["safety"] is True
