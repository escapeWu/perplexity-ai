"""Pure unit tests for OpenAI-compatible model discovery and parsing."""

import pytest

from perplexity.model_registry import ModelRegistry
from perplexity.server import utils

EXPECTED_OAI_MODELS = {
    "perplexity-search",
    "sonar-2",
    "gpt-5-6-terra",
    "claude-sonnet-5",
    "gemini-3-7-flash",
    "grok-4-6",
    "perplexity-thinking",
    "gpt-5-6-terra-thinking",
    "claude-sonnet-5-thinking",
    "gemini-3-7-flash-thinking",
    "kimi-k3-thinking",
    "glm-5-2-thinking",
    "grok-4-6-thinking",
    "nemotron-3-ultra-thinking",
    "perplexity-deepsearch",
}


@pytest.fixture(autouse=True)
def use_repository_model_defaults(tmp_path, monkeypatch) -> None:
    """Keep pure utility tests independent from a developer's runtime cache."""
    registry = ModelRegistry(cache_path=tmp_path / "models.json")
    monkeypatch.setattr(utils, "get_model_registry", lambda: registry)


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
            "base_model_id",
            "thinking_model_id",
            "supports_thinking",
            "thinking",
            "thinking_only",
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


def test_thinking_flag_selects_paired_dynamic_model() -> None:
    assert utils.parse_oai_model_with_thinking("gpt-5-6-terra", True) == (
        "reasoning",
        "gpt-5.6-terra-thinking",
        "gpt-5-6-terra-thinking",
    )
    assert utils.parse_oai_model_with_thinking("gemini-3-7-flash", True) == (
        "reasoning",
        "gemini-3.7-flash-thinking",
        "gemini-3-7-flash-thinking",
    )
    assert utils.parse_oai_model_with_thinking("grok-4-6", True) == (
        "reasoning",
        "grok-4.6-thinking",
        "grok-4-6-thinking",
    )


def test_thinking_flag_selects_default_reasoning_model() -> None:
    assert utils.parse_oai_model_with_thinking("perplexity-search", True) == (
        "reasoning",
        None,
        "perplexity-thinking",
    )


def test_thinking_flag_rejects_model_without_reasoning_variant() -> None:
    with pytest.raises(ValueError, match="does not support thinking"):
        utils.parse_oai_model_with_thinking("sonar-2", True)
