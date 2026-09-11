from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from src.agents.state import OrderState
from src.testing_agent.failure_analyzer import analyze_failure
from src.testing_agent.models import GenerationRequest
from src.testing_agent.regression import recommend_regression_tests
from src.testing_agent.service import generate_testing_plan
from src.testing_agent.test_generator import generate_test_cases
from src.testing_agent.requirement_analyzer import analyze_requirement


def _serialize_case(case) -> dict:
    return {
        "test_case_id": case.test_case_id,
        "title": case.title,
        "scenario_id": case.scenario_id,
        "test_type": case.test_type,
        "priority": case.priority,
        "preconditions": list(case.preconditions),
        "steps": list(case.steps),
        "expected_result": case.expected_result,
        "tags": list(case.tags),
        "automation_candidate": case.automation_candidate,
    }


@tool
def generate_ai_test_cases(
    requirement: str,
    state: Annotated[OrderState, InjectedState],
) -> dict:
    """Generate structured QA test cases from a requirement."""

    request = GenerationRequest(
        requirement=requirement,
        include_negative=True,
        include_edge_cases=True,
        max_cases=10,
    )

    plan = generate_testing_plan(request)

    return {
        "requirement": requirement,
        "scenario_count": len(plan["scenarios"]),
        "test_case_count": len(plan["test_cases"]),
        "test_cases": [_serialize_case(case) for case in plan["test_cases"]],
        "authenticated_context": bool(state.get("user_id")),
    }


@tool
def generate_ai_edge_cases(
    requirement: str,
    state: Annotated[OrderState, InjectedState],
) -> dict:
    """Generate negative, boundary, authorization, and state-integrity test cases."""

    scenarios = analyze_requirement(requirement)

    cases = generate_test_cases(
        scenarios,
        include_negative=True,
        include_edge_cases=True,
        max_cases=50,
    )

    edge_cases = [
        case
        for case in cases
        if (
            case.test_type in {"negative", "edge-case"}
            or any(
                tag in {
                    "security",
                    "authorization",
                    "authentication",
                    "boundary",
                    "validation",
                    "regression",
                }
                for tag in case.tags
            )
        )
    ]

    return {
        "requirement": requirement,
        "test_case_count": len(edge_cases),
        "test_cases": [_serialize_case(case) for case in edge_cases],
        "authenticated_context": bool(state.get("user_id")),
    }


@tool
def analyze_ai_test_failure(
    test_case: str,
    expected_result: str,
    actual_result: str,
    error: str,
    state: Annotated[OrderState, InjectedState],
) -> dict:
    """Analyze a failed AI-generated test and identify likely root cause."""

    return {
        "test_case": test_case,
        "expected_result": expected_result,
        "actual_result": actual_result,
        "error": error,
        "analysis": analyze_failure(
            test_case=test_case,
            expected_result=expected_result,
            actual_result=actual_result,
            error=error,
        ),
    }


@tool
def recommend_ai_regression_tests(
    changed_area: str,
    changed_behavior: str,
    state: Annotated[OrderState, InjectedState],
) -> dict:
    """Recommend regression tests affected by a changed area or behavior."""

    return {
        "changed_area": changed_area,
        "changed_behavior": changed_behavior,
        "recommendations": recommend_regression_tests(
            changed_area=changed_area,
            changed_behavior=changed_behavior,
        ),
    }
