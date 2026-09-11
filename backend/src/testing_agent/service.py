"""Testing-agent orchestration service."""

from src.testing_agent.models import GenerationRequest, TestScenario, TestCase
from src.testing_agent.requirement_analyzer import analyze_requirement
from src.testing_agent.test_generator import generate_test_cases


def generate_testing_plan(request: GenerationRequest) -> dict:
    scenarios: list[TestScenario] = analyze_requirement(request.requirement)

    cases: list[TestCase] = generate_test_cases(
        scenarios,
        include_negative=request.include_negative,
        include_edge_cases=request.include_edge_cases,
        max_cases=request.max_cases,
    )

    return {
        "requirement": request.requirement,
        "scenarios": scenarios,
        "test_cases": cases,
    }


