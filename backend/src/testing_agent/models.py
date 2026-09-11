"""AI testing agent domain models."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TestScenario:
    scenario_id: str
    title: str
    objective: str
    priority: str = "medium"
    preconditions: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    expected_result: str = ""
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TestCase:
    test_case_id: str
    title: str
    scenario_id: str
    test_type: str
    priority: str
    preconditions: tuple[str, ...]
    steps: tuple[str, ...]
    expected_result: str
    tags: tuple[str, ...] = ()
    automation_candidate: bool = True


@dataclass(frozen=True)
class GenerationRequest:
    requirement: str
    context: str = ""
    include_negative: bool = True
    include_edge_cases: bool = True
    max_cases: int = 10
