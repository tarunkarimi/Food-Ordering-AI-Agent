"""Deterministic failure analysis for the AI testing agent."""

from typing import Any


def analyze_failure(
    *,
    test_case: str,
    expected_result: str,
    actual_result: str,
    error: str,
) -> dict[str, Any]:
    """Analyze a failed test and classify the most likely failure area."""

    text = " ".join(
        value.lower()
        for value in (test_case, expected_result, actual_result, error)
        if value
    )

    categories: list[str] = []
    recommendations: list[str] = []

    if any(word in text for word in ("unauthorized", "forbidden", "401", "403", "permission", "authentication")):
        categories.append("authentication_authorization")
        recommendations.append(
            "Verify authentication state, authorization checks, session validity, "
            "and resource ownership enforcement."
        )

    if any(word in text for word in ("cart", "order", "checkout", "payment", "state", "mutation")):
        categories.append("state_transaction")
        recommendations.append(
            "Compare state before and after the operation and verify that only "
            "the intended mutation occurred."
        )

    if any(word in text for word in ("validation", "invalid", "malformed", "422", "400")):
        categories.append("input_validation")
        recommendations.append(
            "Verify validation rules, boundary handling, and the returned error response."
        )

    if any(word in text for word in ("timeout", "connection", "network", "500", "502", "503")):
        categories.append("infrastructure")
        recommendations.append(
            "Check service availability, dependency failures, timeouts, and server logs."
        )

    if not categories:
        categories.append("functional_behavior")
        recommendations.append(
            "Compare the actual behavior with the requirement and inspect the "
            "implementation path exercised by the test."
        )

    return {
        "classification": categories[0],
        "categories": categories,
        "likely_root_cause": recommendations[0],
        "recommendations": recommendations,
        "severity": (
            "critical"
            if "authentication_authorization" in categories
            or "state_transaction" in categories
            else "high"
        ),
    }
