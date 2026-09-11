"""Deterministic requirement analysis for the AI testing agent."""

import re

from src.testing_agent.models import TestScenario


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def analyze_requirement(requirement: str) -> list[TestScenario]:
    requirement = _clean(requirement)

    if not requirement:
        return []

    lower = requirement.lower()

    scenarios: list[TestScenario] = [
        TestScenario(
            scenario_id="TS-001",
            title="Primary happy-path behavior",
            objective=f"Validate the primary behavior described by the requirement: {requirement}",
            priority="high",
            steps=(
                f"Set up the preconditions implied by: {requirement}",
                "Execute the primary user action.",
                "Observe the resulting system behavior.",
            ),
            expected_result="The requested behavior completes successfully and matches the requirement.",
            tags=("happy-path",),
        ),
        TestScenario(
            scenario_id="TS-002",
            title="Invalid input handling",
            objective="Verify that invalid or incomplete input is rejected safely.",
            priority="high",
            steps=(
                "Provide missing, malformed, or invalid input.",
                "Submit the request.",
                "Inspect the validation response and resulting state.",
            ),
            expected_result="Invalid input is rejected with a clear validation response and no unintended state mutation.",
            tags=("negative", "validation"),
        ),
        TestScenario(
            scenario_id="TS-003",
            title="Boundary behavior",
            objective="Verify minimum, maximum, empty, and boundary-value behavior.",
            priority="medium",
            steps=(
                "Exercise the minimum valid value.",
                "Exercise the maximum valid value.",
                "Exercise one value just outside the valid boundary.",
            ),
            expected_result="Boundary values follow the documented rules and out-of-range values are rejected safely.",
            tags=("edge-case", "boundary"),
        ),
    ]

    if any(word in lower for word in ("auth", "login", "password", "otp", "session", "permission")):
        scenarios.append(
            TestScenario(
                scenario_id="TS-004",
                title="Authentication and authorization behavior",
                objective="Verify authenticated, unauthenticated, expired-session, and unauthorized access behavior.",
                priority="critical",
                steps=(
                    "Execute the flow without authentication.",
                    "Execute the flow with valid authentication.",
                    "Execute the flow with expired or invalid authentication.",
                    "Attempt access to another user's protected resource.",
                ),
                expected_result="Protected operations require valid authorization and never expose another user's data.",
                tags=("security", "authorization", "authentication"),
            )
        )

    if any(word in lower for word in ("cart", "order", "checkout", "payment", "reorder")):
        scenarios.append(
            TestScenario(
                scenario_id="TS-005",
                title="State and transaction integrity",
                objective="Verify that state changes occur exactly as intended during the operation.",
                priority="critical",
                steps=(
                    "Capture the initial state.",
                    "Perform the requested operation.",
                    "Inspect the resulting state.",
                    "Retry the operation where duplicate submission is relevant.",
                ),
                expected_result="State transitions are correct, duplicate actions are handled safely, and unrelated state is unchanged.",
                tags=("state", "transaction", "regression"),
            )
        )

    return scenarios
