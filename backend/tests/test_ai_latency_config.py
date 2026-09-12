from unittest.mock import patch

import src.agents.nodes.chatbot as chatbot_module


def test_ai_request_timeout_is_configured():
    assert chatbot_module._model.timeout == 30.0


def test_ai_request_timeout_is_configurable():
    with patch.object(
        chatbot_module.config,
        "AI_REQUEST_TIMEOUT_SECONDS",
        17.5,
    ):
        assert chatbot_module.config.AI_REQUEST_TIMEOUT_SECONDS == 17.5
