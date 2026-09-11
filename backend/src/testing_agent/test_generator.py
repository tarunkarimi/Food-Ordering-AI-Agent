"""Test-case generation from structured test scenarios."""

from src.testing_agent.models import TestCase, TestScenario


def generate_test_cases(
    scenarios: list[TestScenario],
    *,
    include_negative: bool = True,
    include_edge_cases: bool = True,
    max_cases: int = 10,
) -> list[TestCase]:
    cases: list[TestCase] = []

    for scenario in scenarios:
        cases.append(
            TestCase(
                test_case_id=f"TC-{len(cases) + 1:03d}",
                title=scenario.title,
                scenario_id=scenario.scenario_id,
                test_type="functional",
                priority=scenario.priority,
                preconditions=scenario.preconditions,
                steps=scenario.steps,
                expected_result=scenario.expected_result,
                tags=scenario.tags,
            )
        )

        if include_negative and "negative" in scenario.tags:
            cases.append(
                TestCase(
                    test_case_id=f"TC-{len(cases) + 1:03d}",
                    title=f"{scenario.title} - rejection",
                    scenario_id=scenario.scenario_id,
                    test_type="negative",
                    priority="high",
                    preconditions=scenario.preconditions,
                    steps=(
                        *scenario.steps,
                        "Verify that no unintended mutation occurred.",
                    ),
                    expected_result=(
                        "The request is rejected safely, with an actionable "
                        "validation response and no unintended side effects."
                    ),
                    tags=(*scenario.tags, "safety"),
                )
            )

        if include_edge_cases and "edge-case" in scenario.tags:
            cases.append(
                TestCase(
                    test_case_id=f"TC-{len(cases) + 1:03d}",
                    title=f"{scenario.title} - boundary",
                    scenario_id=scenario.scenario_id,
                    test_type="edge-case",
                    priority="medium",
                    preconditions=scenario.preconditions,
                    steps=(
                        "Use the exact boundary value.",
                        "Use the nearest valid value.",
                        "Use the nearest invalid value.",
                    ),
                    expected_result=(
                        "Boundary values are handled according to the "
                        "requirement without data corruption."
                    ),
                    tags=(*scenario.tags, "boundary"),
                )
            )

    return cases[: max(1, max_cases)]
