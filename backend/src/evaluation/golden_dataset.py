"""Golden evaluation dataset loading."""

import json
from pathlib import Path

from src.evaluation.models import EvaluationCase


_DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "evaluation"
    / "golden_cases.json"
)


def load_golden_cases() -> list[EvaluationCase]:
    """Load all version-controlled golden evaluation cases."""

    with _DATASET_PATH.open("r", encoding="utf-8-sig") as file:
        raw_cases = json.load(file)

    if not isinstance(raw_cases, list):
        raise ValueError("Golden evaluation dataset must be a JSON list.")

    cases: list[EvaluationCase] = []

    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise ValueError(
                "Each golden evaluation case must be an object."
            )

        cases.append(
            EvaluationCase(
                case_id=raw_case["case_id"],
                category=raw_case["category"],
                user_message=raw_case["user_message"],
                expected_intent=raw_case["expected_intent"],
                authenticated=raw_case.get(
                    "authenticated",
                    True,
                ),
                expected_tools=tuple(
                    raw_case.get("expected_tools", [])
                ),
                forbidden_tools=tuple(
                    raw_case.get("forbidden_tools", [])
                ),
                required_response_terms=tuple(
                    raw_case.get(
                        "required_response_terms",
                        [],
                    )
                ),
                forbidden_response_terms=tuple(
                    raw_case.get(
                        "forbidden_response_terms",
                        [],
                    )
                ),
                expected_cart_mutation=raw_case.get(
                    "expected_cart_mutation",
                    False,
                ),
                expected_order_mutation=raw_case.get(
                    "expected_order_mutation",
                    False,
                ),
                requires_personalization=raw_case.get(
                    "requires_personalization",
                    False,
                ),
                metadata=raw_case.get(
                    "metadata",
                    {},
                ),
            )
        )

    return cases
