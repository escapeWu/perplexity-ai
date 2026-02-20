"""
Utility functions for Perplexity server module.

This module provides helper functions for validation, OpenAI-compatible API,
and other common operations used by the server.
"""

from typing import Any, Dict, List, Optional, Tuple

try:
    from ..exceptions import ValidationError
    from ..config import (
        SEARCH_MODES,
        SEARCH_SOURCES,
        MODEL_MAPPINGS,
    )
except ImportError:
    from perplexity.exceptions import ValidationError
    from perplexity.config import (
        SEARCH_MODES,
        SEARCH_SOURCES,
        MODEL_MAPPINGS,
    )

# ==================== OpenAI-Compatible API Helpers ====================

# Cache for OAI model mapping
_OAI_MODEL_MAP: Dict[str, Tuple[str, Optional[str]]] = {}


def sanitize_oai_model_name(name: str) -> str:
    """
    Sanitize model name for OpenAI compatibility.
    - Replace dots with dashes: "gpt-5.2" -> "gpt-5-2"
    - Replace spaces with dashes: "deep research" -> "deep-research"
    - Convert to lowercase
    """
    return name.lower().replace(".", "-").replace(" ", "-")


def _oai_id(mode: str, model_name: Optional[str]) -> str:
    """Compute OAI model ID for a given mode and internal model name."""
    if model_name is None:
        if mode == "reasoning":
            return "perplexity-thinking"
        elif mode == "deep research":
            return "perplexity-deepsearch"
        else:  # auto, pro
            return "perplexity-search"
    sanitized = sanitize_oai_model_name(model_name)
    if mode == "reasoning":
        if sanitized.endswith("-thinking"):
            return sanitized
        elif sanitized.endswith("-reasoning"):
            return sanitized[: -len("-reasoning")] + "-thinking"
        else:
            return sanitized + "-thinking"
    return sanitized  # pro/auto: no suffix


def build_oai_model_map() -> Dict[str, Tuple[str, Optional[str]]]:
    """Build reverse mapping from OAI model ID to (mode, model)."""
    mapping: Dict[str, Tuple[str, Optional[str]]] = {}

    for mode in ["auto", "pro", "reasoning", "deep research"]:
        for model_name in MODEL_MAPPINGS.get(mode, {}).keys():
            oai_id = _oai_id(mode, model_name)
            # pro overwrites auto for the same default "perplexity-search"
            if oai_id not in mapping or mode == "pro":
                mapping[oai_id] = (mode, model_name)

    return mapping


def parse_oai_model(model_id: str) -> Tuple[str, Optional[str]]:
    """
    Parse OAI model ID to (mode, model).

    Args:
        model_id: OpenAI-format model ID (e.g., "perplexity-search", "gpt-5-2-thinking")

    Returns:
        Tuple of (mode, model) where model can be None for default models

    Raises:
        ValueError: If model ID is not recognized
    """
    global _OAI_MODEL_MAP
    if not _OAI_MODEL_MAP:
        _OAI_MODEL_MAP = build_oai_model_map()

    if model_id not in _OAI_MODEL_MAP:
        raise ValueError(f"Unknown model: {model_id}")

    return _OAI_MODEL_MAP[model_id]


def generate_oai_models() -> List[Dict[str, Any]]:
    """
    Generate OpenAI-compatible model list from MODEL_MAPPINGS.

    Returns:
        List of model objects with id, object, created, owned_by fields
    """
    models: List[Dict[str, Any]] = []
    seen_ids: set = set()
    created_timestamp = 1700000000  # Static timestamp

    # Skip "auto" — "pro" generates the same default perplexity-search
    for mode in ["pro", "reasoning", "deep research"]:
        for model_name in MODEL_MAPPINGS.get(mode, {}).keys():
            oai_id = _oai_id(mode, model_name)

            if oai_id in seen_ids:
                continue
            seen_ids.add(oai_id)

            models.append({
                "id": oai_id,
                "object": "model",
                "created": created_timestamp,
                "owned_by": "perplexity"
            })

    return models


def create_oai_error_response(message: str, error_type: str) -> Dict[str, Any]:
    """
    Create standardized OpenAI-format error response body.

    Args:
        message: Error message
        error_type: Error type (e.g., "invalid_request_error", "api_error")

    Returns:
        Error response dict in OpenAI format
    """
    return {"error": {"message": message, "type": error_type}}


# ==================== Validation Functions ====================

def validate_search_params(
    mode: str, model: Optional[str], sources: list, own_account: bool = False
) -> None:
    """
    Validate search parameters.

    Args:
        mode: Search mode
        model: Model name (optional)
        sources: List of sources
        own_account: Whether using own account

    Raises:
        ValidationError: If parameters are invalid

    Example:
        >>> validate_search_params("pro", "gpt-4.5", ["web"], True)
    """
    # Validate mode - guard against None SEARCH_MODES
    if SEARCH_MODES is None or mode not in SEARCH_MODES:
        valid_modes = ', '.join(SEARCH_MODES) if SEARCH_MODES else "auto, pro, reasoning, deep research"
        raise ValidationError(f"Invalid mode '{mode}'. Must be one of: {valid_modes}")

    # Validate model - guard against None MODEL_MAPPINGS
    if model is not None:
        if MODEL_MAPPINGS is None:
            valid_models = [None]
        else:
            valid_models = list(MODEL_MAPPINGS.get(mode, {}).keys())
        if model not in valid_models:
            raise ValidationError(
                f"Invalid model '{model}' for mode '{mode}'. "
                f"Valid models: {', '.join(str(m) for m in valid_models)}"
            )

    # Check if model requires own account
    if model is not None and not own_account:
        raise ValidationError(
            "Model selection requires an account with cookies. "
            "Initialize Client with cookies parameter."
        )

    # Validate sources - guard against None SEARCH_SOURCES
    if SEARCH_SOURCES is None:
        valid_sources_list = ["web", "scholar", "social"]
    else:
        valid_sources_list = SEARCH_SOURCES
    invalid_sources = [s for s in sources if s not in valid_sources_list]
    if invalid_sources:
        raise ValidationError(
            f"Invalid sources: {', '.join(invalid_sources)}. "
            f"Valid sources: {', '.join(valid_sources_list)}"
        )

    if not sources:
        raise ValidationError("At least one source must be specified")


def validate_query_limits(
    copilot_remaining: int,
    file_upload_remaining: int,
    mode: str,
    files_count: int,
) -> None:
    """
    Validate query and file upload limits.

    Args:
        copilot_remaining: Remaining copilot queries
        file_upload_remaining: Remaining file uploads
        mode: Search mode
        files_count: Number of files to upload

    Raises:
        ValidationError: If limits are exceeded

    Example:
        >>> validate_query_limits(5, 10, "pro", 2)
    """
    # Check copilot queries
    if mode in ["pro", "reasoning", "deep research"] and copilot_remaining <= 0:
        raise ValidationError(
            f"No remaining enhanced queries for mode '{mode}'. "
            f"Create a new account or use mode='auto'."
        )

    # Check file uploads
    if files_count > 0 and file_upload_remaining < files_count:
        raise ValidationError(
            f"Insufficient file uploads. Requested: {files_count}, "
            f"Available: {file_upload_remaining}"
        )


def validate_file_data(files: dict) -> None:
    """
    Validate file data dictionary.

    Args:
        files: Dictionary with filenames as keys and file data as values

    Raises:
        ValidationError: If file data is invalid

    Example:
        >>> validate_file_data({"doc.pdf": b"..."})
    """
    if not isinstance(files, dict):
        raise ValidationError("Files must be a dictionary")

    for filename, data in files.items():
        if not isinstance(filename, str):
            raise ValidationError(f"Filename must be string, got {type(filename)}")

        if not filename.strip():
            raise ValidationError("Filename cannot be empty")

        if not isinstance(data, (bytes, str)):
            raise ValidationError(f"File data must be bytes or string, got {type(data)}")


def sanitize_query(query: str) -> str:
    """
    Sanitize and validate query string.

    Args:
        query: Query string

    Returns:
        Sanitized query string

    Raises:
        ValidationError: If query is invalid

    Example:
        >>> sanitize_query("  What is AI?  ")
        'What is AI?'
    """
    if not isinstance(query, str):
        raise ValidationError(f"Query must be string, got {type(query)}")

    query = query.strip()

    if not query:
        raise ValidationError("Query cannot be empty")

    if len(query) > 10000:
        raise ValidationError("Query is too long (max 10000 characters)")

    return query
