"""Bridge between testing-agent QA output and the deterministic evaluator."""

from src.evaluation.models import AgentEvaluationTrace, EvaluationCase
from src.evaluation.runner import evaluate_case
from src.testing_agent.models import TestCase


def build_testing_agent_trace(
    *,
    response: str,
    test_cases: list[TestCase],
    predicted_intent: str | None = None,
    tools_called: tuple[str, ...] = (),
    authenticated: bool = True,
    personalization_used: bool = False,
) -> AgentEvaluationTrace:
    """Convert observable testing-agent execution into an evaluator trace."""

    cart_mutated = any(
        any(
            tag in {"cart", "mutation", "state"}
            for tag in case.tags
        )
        for case in test_cases
    )

    order_mutated = any(
        any(
            tag in {"order", "checkout", "transaction"}
            for tag in case.tags
        )
        for case in test_cases
    )

    return AgentEvaluationTrace(
        response=response,
        predicted_intent=predicted_intent,
        tools_called=tools_called,
        cart_mutated=cart_mutated,
        order_mutated=order_mutated,
        authenticated=authenticated,
        personalization_used=personalization_used,
    )


def evaluate_testing_agent_case(
    case: EvaluationCase,
    trace: AgentEvaluationTrace,
):
    """Evaluate one testing-agent execution using the #39 framework."""

    return evaluate_case(case, trace)
