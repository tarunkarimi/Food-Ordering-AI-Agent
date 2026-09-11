from src.testing_agent.models import GenerationRequest
from src.testing_agent.requirement_analyzer import analyze_requirement
from src.testing_agent.service import generate_testing_plan


def test_requirement_generates_happy_path_negative_and_boundary():
    scenarios = analyze_requirement(
        "User can add a product to the cart and checkout."
    )

    titles = {scenario.title for scenario in scenarios}

    assert "Primary happy-path behavior" in titles
    assert "Invalid input handling" in titles
    assert "Boundary behavior" in titles
    assert "State and transaction integrity" in titles


def test_auth_requirement_adds_security_scenario():
    scenarios = analyze_requirement(
        "Authenticated users can view their order history."
    )

    assert any(
        scenario.scenario_id == "TS-004"
        for scenario in scenarios
    )


def test_empty_requirement_returns_no_scenarios():
    assert analyze_requirement("") == []


def test_generate_testing_plan_returns_structured_cases():
    result = generate_testing_plan(
        GenerationRequest(
            requirement="User can add a product to the cart.",
            max_cases=6,
        )
    )

    assert result["requirement"]
    assert result["scenarios"]
    assert result["test_cases"]
    assert len(result["test_cases"]) <= 6

    for test_case in result["test_cases"]:
        assert test_case.test_case_id.startswith("TC-")
        assert test_case.expected_result
        assert test_case.scenario_id


