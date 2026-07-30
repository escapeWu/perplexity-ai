"""Pure unit tests for OpenAI-compatible model discovery and parsing."""

from perplexity.server import utils

EXPECTED_OAI_MODELS = {
    "perplexity-search",
    "sonar-2",
    "gpt-5-6-terra",
    "claude-sonnet-5",
    "gemini-3-1-pro",
    "grok-4-5",
    "perplexity-thinking",
    "gpt-5-6-terra-thinking",
    "claude-sonnet-5-thinking",
    "gemini-3-1-pro-thinking",
    "kimi-k3-thinking",
    "glm-5-2-thinking",
    "grok-4-5-thinking",
    "nemotron-3-ultra-thinking",
    "perplexity-deepsearch",
}


def test_generate_oai_models_exposes_current_non_max_lineup() -> None:
    models = utils.generate_oai_models()

    assert {model["id"] for model in models} == EXPECTED_OAI_MODELS
    assert all(
        {
            "id",
            "object",
            "created",
            "owned_by",
            "label",
            "description",
            "subscription_tier",
            "mode",
        }
        <= model.keys()
        for model in models
    )


def test_oai_model_ids_round_trip_to_internal_mappings() -> None:
    expected_mapping = utils.build_oai_model_map()
    utils._OAI_MODEL_MAP.clear()

    assert set(expected_mapping) == EXPECTED_OAI_MODELS | {"sonar"}
    for model_id, mode_and_model in expected_mapping.items():
        assert utils.parse_oai_model(model_id) == mode_and_model


def test_reasoning_only_names_receive_thinking_suffix() -> None:
    assert utils._oai_id("reasoning", "glm-5.2") == "glm-5-2-thinking"
    assert utils._oai_id("reasoning", "nemotron-3-ultra") == "nemotron-3-ultra-thinking"
    assert utils._oai_id("reasoning", "gpt-5.6-terra-thinking") == "gpt-5-6-terra-thinking"
