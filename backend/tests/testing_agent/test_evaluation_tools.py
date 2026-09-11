from src.agents.tools.testing import (
    analyze_ai_test_failure,
    generate_ai_edge_cases,
    generate_ai_test_cases,
    recommend_ai_regression_tests,
)


def test_testing_tools_are_registered_and_callable():
    assert generate_ai_test_cases.name == "generate_ai_test_cases"
    assert generate_ai_edge_cases.name == "generate_ai_edge_cases"
    assert analyze_ai_test_failure.name == "analyze_ai_test_failure"
    assert recommend_ai_regression_tests.name == "recommend_ai_regression_tests"


def test_failure_analysis_tool_detects_authorization_failure():
    result = analyze_ai_test_failure.invoke(
        {
            "test_case": "Access another user's order",
            "expected_result": "Request is rejected with 403.",
            "actual_result": "Order data was returned.",
            "error": "Authorization bypass",
            "state": {"user_id": 1},
        }
    )

    assert result["analysis"]["classification"] == "authentication_authorization"


def test_regression_tool_detects_checkout_risk():
    result = recommend_ai_regression_tests.invoke(
        {
            "changed_area": "checkout service",
            "changed_behavior": "cart to order transaction",
            "state": {"user_id": 1},
        }
    )

    titles = [item["title"] for item in result["recommendations"]]

    assert any("checkout" in title.lower() for title in titles)
    assert any(
        item["priority"] == "critical"
        for item in result["recommendations"]
    )


def test_testing_tools_do_not_mutate_state():
    state = {
        "user_id": 123,
        "cart": {"items": []},
    }

    before = repr(state)

    generate_ai_test_cases.invoke(
        {
            "requirement": "Authenticated users can add food to cart.",
            "state": state,
        }
    )

    assert repr(state) == before
