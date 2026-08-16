"""Utility tests with console-like output for user visibility."""

import pytest

from perplexity.config import MODEL_MAPPINGS
from perplexity.exceptions import ValidationError
from perplexity.server.app import extract_clean_result
from perplexity.server.utils import sanitize_query, validate_search_params


def test_sanitize_query_trims_and_validates() -> None:
    print("console.log -> testing sanitize_query behavior")
    assert sanitize_query("  hello world  ") == "hello world"
    with pytest.raises(ValidationError):
        sanitize_query("")


def test_validate_search_params_requires_own_account() -> None:
    print("console.log -> validating search params requirements")
    validate_search_params("auto", None, ["web"], own_account=False)
    with pytest.raises(ValidationError):
        validate_search_params("pro", "sonar-2", ["web"], own_account=False)


def test_validate_search_params_accepts_all_configured_models() -> None:
    print("console.log -> validating every configured model")
    for mode, mappings in MODEL_MAPPINGS.items():
        for model in mappings:
            validate_search_params(mode, model, ["web"], own_account=True)

    with pytest.raises(ValidationError):
        validate_search_params("pro", "gpt-5.4", ["web"], own_account=True)


def test_extract_clean_result_preserves_model_downgrade_metadata() -> None:
    result = extract_clean_result(
        {
            "answer": "fallback answer",
            "display_model": "turbo",
            "user_selected_model": "grok46medium",
            "model_downgraded": True,
            "requested_model": "grok46medium",
            "effective_model": "turbo",
        }
    )

    assert result == {
        "answer": "fallback answer",
        "sources": [],
        "display_model": "turbo",
        "user_selected_model": "grok46medium",
        "model_downgraded": True,
        "requested_model": "grok46medium",
        "effective_model": "turbo",
    }
