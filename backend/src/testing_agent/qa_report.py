"""Structured QA reporting for the AI testing agent."""

from dataclasses import dataclass, field
from typing import Any

from src.testing_agent.models import TestCase, TestScenario


@dataclass(frozen=True)
class QAReport:
    requirement: str
    scenario_count: int
    test_case_count: int
    high_priority_count: int
    critical_count: int
    negative_count: int
    edge_case_count: int
    security_count: int
    automation_candidates: int
    scenarios: tuple[dict[str, Any], ...] = ()
    test_cases: tuple[dict[str, Any], ...] = ()
    risks: tuple[str, ...] = ()
    coverage_areas: tuple[str, ...] = ()


def _scenario_dict(scenario: TestScenario) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "title": scenario.title,
        "objective": scenario.objective,
        "priority": scenario.priority,
        "preconditions": list(scenario.preconditions),
        "steps": list(scenario.steps),
        "expected_result": scenario.expected_result,
        "tags": list(scenario.tags),
    }


def _case_dict(case: TestCase) -> dict[str, Any]:
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


def build_qa_report(
    requirement: str,
    scenarios: list[TestScenario],
    test_cases: list[TestCase],
) -> QAReport:
    tags = {
        tag
        for scenario in scenarios
        for tag in scenario.tags
    }

    coverage = {
        "functional",
        "negative",
        "boundary",
        "security",
        "authorization",
        "authentication",
        "state",
        "transaction",
    }

    coverage_areas = tuple(sorted(tags & coverage))

    risks: list[str] = []

    if "security" in tags or "authorization" in tags:
        risks.append("Authentication and authorization behavior requires regression coverage.")

    if "transaction" in tags or "state" in tags:
        risks.append("State-changing behavior requires mutation and duplicate-submission checks.")

    if "negative" in tags:
        risks.append("Invalid-input paths must reject safely without unintended side effects.")

    return QAReport(
        requirement=requirement,
        scenario_count=len(scenarios),
        test_case_count=len(test_cases),
        high_priority_count=sum(
            case.priority == "high" for case in test_cases
        ),
        critical_count=sum(
            case.priority == "critical" for case in test_cases
        ),
        negative_count=sum(
            case.test_type == "negative" for case in test_cases
        ),
        edge_case_count=sum(
            case.test_type == "edge-case" for case in test_cases
        ),
        security_count=sum(
            bool(
                {
                    "security",
                    "authorization",
                    "authentication",
                }
                & set(case.tags)
            )
            for case in test_cases
        ),
        automation_candidates=sum(
            case.automation_candidate for case in test_cases
        ),
        scenarios=tuple(_scenario_dict(scenario) for scenario in scenarios),
        test_cases=tuple(_case_dict(case) for case in test_cases),
        risks=tuple(risks),
        coverage_areas=coverage_areas,
    )
