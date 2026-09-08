"""Command-line entry point for deterministic agent evaluation."""

from src.evaluation.runner_cli import format_evaluation_report


def main() -> int:
    """Run the evaluation command.

    The current deterministic checkpoint uses the golden baseline traces.
    Live LangGraph trace collection will be connected in the next
    evaluation integration step.
    """

    from src.evaluation.golden_dataset import load_golden_cases
    from src.evaluation.models import AgentEvaluationTrace

    cases = load_golden_cases()

    traces = {
        case.case_id: AgentEvaluationTrace(
            response="Evaluation response.",
            predicted_intent=case.expected_intent,
            tools_called=case.expected_tools,
            cart_mutated=case.expected_cart_mutation,
            order_mutated=case.expected_order_mutation,
            authenticated=case.authenticated,
            personalization_used=case.requires_personalization,
        )
        for case in cases
    }

    print(format_evaluation_report(traces))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
