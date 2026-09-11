from src.testing_agent.requirement_analyzer import analyze_requirement
from src.testing_agent.test_generator import generate_test_cases


def test_negative_cases_are_generated():
    scenarios = analyze_requirement("A user submits a form.")

    cases = generate_test_cases(
        scenarios,
        include_negative=True,
        include_edge_cases=False,
        max_cases=10,
    )

    assert any(case.test_type == "negative" for case in cases)


def test_edge_cases_can_be_disabled():
    scenarios = analyze_requirement("A user submits a form.")

    cases = generate_test_cases(
        scenarios,
        include_negative=False,
        include_edge_cases=False,
        max_cases=10,
    )

    assert all(case.test_type == "functional" for case in cases)


def test_max_cases_is_respected():
    scenarios = analyze_requirement("A user can checkout an order.")

    cases = generate_test_cases(
        scenarios,
        max_cases=3,
    )

    assert len(cases) <= 3
