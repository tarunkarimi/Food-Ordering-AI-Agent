"""Deterministic regression-test recommendation for the AI testing agent."""

from typing import Any


def recommend_regression_tests(
    *,
    changed_area: str,
    changed_behavior: str,
) -> list[dict[str, Any]]:
    """Recommend regression coverage based on changed functionality."""

    area = (changed_area or "").lower()
    behavior = (changed_behavior or "").lower()
    text = f"{area} {behavior}"

    recommendations: list[dict[str, Any]] = []

    def add(test_type: str, title: str, reason: str, priority: str) -> None:
        recommendations.append(
            {
                "test_type": test_type,
                "title": title,
                "reason": reason,
                "priority": priority,
            }
        )

    if any(word in text for word in ("auth", "login", "session", "jwt", "permission", "authorization")):
        add(
            "security",
            "Authenticated and unauthorized access regression",
            "Authentication or authorization behavior changed.",
            "critical",
        )

    if any(word in text for word in ("cart", "checkout", "order", "payment", "reorder")):
        add(
            "transaction",
            "Cart and checkout state-integrity regression",
            "Order or cart state can be affected by the changed behavior.",
            "critical",
        )

    if any(word in text for word in ("menu", "recommend", "personalization", "preference")):
        add(
            "functional",
            "Menu and personalized recommendation regression",
            "Recommendation or menu-dependent behavior may be affected.",
            "high",
        )

    if any(word in text for word in ("api", "endpoint", "route", "response")):
        add(
            "api",
            "API contract regression",
            "An API-facing area or response behavior changed.",
            "high",
        )

    if not recommendations:
        add(
            "functional",
            "Changed-behavior regression",
            "The changed area requires validation of its primary behavior.",
            "medium",
        )

    add(
        "negative",
        "Invalid-input and boundary regression",
        "Changes should not break rejection or boundary behavior.",
        "high",
    )

    return recommendations
