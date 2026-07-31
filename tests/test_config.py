"""Smoke tests for perplexity.config with console-style output."""

from perplexity import config


def test_api_endpoints_structure() -> None:
    print("console.log -> validating API endpoints and versions")
    assert config.API_BASE_URL.startswith("https://")
    assert config.API_VERSION.count(".") >= 1
    assert config.ENDPOINT_AUTH_SESSION.startswith(config.API_BASE_URL)
    assert config.ENDPOINT_SSE_ASK.startswith(config.API_BASE_URL)
    assert config.ENDPOINT_UPLOAD_URL.startswith(config.API_BASE_URL)
    assert config.OFFICIAL_MODELS_CONFIG_URL.startswith(config.API_BASE_URL)
    assert "config/v2" in config.OFFICIAL_MODELS_CONFIG_URL
    assert config.DEFAULT_MODELS_CONFIG_URL.startswith(
        "https://raw.githubusercontent.com/escapeWu/perplexity-ai/"
    )
    assert config.ENDPOINT_MODELS_CONFIG.startswith(("http://", "https://"))
    assert config.MODEL_CONFIG_CACHE_TTL >= 60


def test_search_modes_and_models() -> None:
    print("console.log -> checking search modes and model mappings")
    assert set(config.SEARCH_MODES) >= {"auto", "pro", "reasoning"}
    assert config.MODEL_MAPPINGS["pro"] == {
        None: "pplx_pro",
        "sonar-2": "experimental",
        "sonar": "experimental",
        "gpt-5.6-terra": "gpt56_terra",
        "claude-sonnet-5": "claude50sonnet",
        "gemini-3.1-pro": "gemini31pro_high",
        "grok-4.5": "grok45low",
    }
    assert config.MODEL_MAPPINGS["reasoning"] == {
        None: "pplx_reasoning",
        "gpt-5.6-terra-thinking": "gpt56_terra_thinking",
        "claude-sonnet-5-thinking": "claude50sonnetthinking",
        "gemini-3.1-pro": "gemini31pro_high",
        "kimi-k3-thinking": "kimik3thinking",
        "glm-5.2": "glm_5_2",
        "grok-4.5-thinking": "grok45medium",
        "nemotron-3-ultra": "nv_nemotron_3_ultra",
    }
    assert "deep research" in config.MODEL_MAPPINGS

    retired_models = {
        "gpt-5.4",
        "gpt-5.4-thinking",
        "claude-4.6-sonnet",
        "claude-4.6-sonnet-thinking",
        "kimi-k2-thinking",
    }
    exposed_models = {
        model
        for mappings in config.MODEL_MAPPINGS.values()
        for model in mappings
        if model is not None
    }
    assert retired_models.isdisjoint(exposed_models)
