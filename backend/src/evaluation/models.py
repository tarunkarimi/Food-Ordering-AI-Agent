"""Data models for deterministic AI-agent evaluations."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvaluationCase:
    """One deterministic golden evaluation scenario."""

    case_id: str
    category: str
    user_message: str
    expected_intent: str
    authenticated: bool = True
    expected_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    required_response_terms: tuple[str, ...] = ()
    forbidden_response_terms: tuple[str, ...] = ()
    expected_cart_mutation: bool = False
    expected_order_mutation: bool = False
    requires_personalization: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentEvaluationTrace:
    """Observable agent execution data used by the evaluator."""

    response: str = ""
    predicted_intent: str | None = None
    tools_called: tuple[str, ...] = ()
    cart_mutated: bool = False
    order_mutated: bool = False
    authenticated: bool = True
    personalization_used: bool = False


@dataclass(frozen=True)
class EvaluationResult:
    """Result of evaluating one agent execution."""

    case_id: str
    passed: bool
    score: float
    failures: tuple[str, ...] = ()
    checks: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationSummary:
    """Aggregate evaluation metrics."""

    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    average_score: float
    intent_accuracy: float
    tool_selection_accuracy: float
    response_quality_rate: float
    safety_pass_rate: float
    mutation_correctness_rate: float
    personalization_accuracy: float
