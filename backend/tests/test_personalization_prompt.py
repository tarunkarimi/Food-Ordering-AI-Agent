from src.agents.prompts.system_prompt import SYSTEM_INSTRUCTION


PROMPT = SYSTEM_INSTRUCTION[1]
PROMPT_LOWER = PROMPT.lower()


def test_personalization_prompt_requires_history_tool():
    assert "get_my_food_preferences" in PROMPT
    assert "what they usually order" in PROMPT_LOWER
    assert "what they have ordered" in PROMPT_LOWER


def test_personalization_prompt_distinguishes_frequency_and_quantity():
    assert '"order_count"' in PROMPT
    assert '"total_quantity"' in PROMPT


def test_personalization_prompt_handles_insufficient_history():
    assert "not enough order history" in PROMPT_LOWER
    assert "do not invent favorites or preferences" in PROMPT_LOWER


def test_personalization_prompt_prevents_unrequested_cart_changes():
    section = PROMPT[
        PROMPT.index("PERSONALIZATION RULES:")
        : PROMPT.index("PERSONALIZATION EXAMPLES:")
    ].lower()

    assert "cart" in section
    assert "automatically" in section
    assert "place an order" in section


def test_personalization_prompt_preserves_current_menu_authority():
    assert "current menu is authoritative for availability and pricing" in PROMPT_LOWER
    assert "historical order prices" in PROMPT_LOWER
    assert "never" in PROMPT_LOWER


def test_personalization_prompt_requires_current_menu_for_purchase():
    section = PROMPT[
        PROMPT.index("PERSONALIZATION RULES:")
        : PROMPT.index("PERSONALIZATION EXAMPLES:")
    ].lower()

    assert "current menu" in section
    assert "historical price" in section


def test_personalization_prompt_hides_internal_tool_fields():
    assert "raw personalization tool output" in PROMPT_LOWER
    assert "orders_analyzed" in PROMPT
    assert "order_count" in PROMPT
    assert "total_quantity" in PROMPT


def test_personalization_prompt_handles_key_user_requests():
    assert 'customer: "what do i usually order?"' in PROMPT_LOWER
    assert "what's my usual?" in PROMPT_LOWER
    assert 'customer: "recommend something based on my orders."' in PROMPT_LOWER
    assert 'customer: "add my usual to the cart."' in PROMPT_LOWER
