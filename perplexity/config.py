"""
Configuration constants for Perplexity AI API.

This module contains all configurable constants used throughout the library.
Modify these values to customize behavior without changing core code.
"""

import logging
import os
from pathlib import Path
from typing import Dict, Optional

# Load environment variables from .env file
from dotenv import load_dotenv

# Try to load .env from multiple locations
_env_locations = [
    Path.cwd() / ".env",  # Current working directory
    Path(__file__).parent.parent / ".env",  # Project root
    Path.home() / ".perplexity" / ".env",  # User home directory
]

for _env_path in _env_locations:
    if _env_path.exists():
        load_dotenv(_env_path)
        break
else:
    # Load from default location if no .env found
    load_dotenv()

# SOCKS Proxy Configuration
# Format: socks5://[user[:pass]@]host[:port][#remark]
# Examples:
#   socks5://127.0.0.1:1080
#   socks5://user:pass@127.0.0.1:1080
#   socks5://user:pass@127.0.0.1:1080#my-proxy
SOCKS_PROXY: Optional[str] = os.getenv("SOCKS_PROXY", None)

_logger = logging.getLogger(__name__)
if SOCKS_PROXY:
    _logger.debug("SOCKS_PROXY loaded: %s", SOCKS_PROXY.split("@")[-1].split("#")[0])
else:
    _logger.debug("SOCKS_PROXY not configured, will use direct connection")

# API Configuration
API_BASE_URL = "https://www.perplexity.ai"
API_VERSION = "2.18"

# Search Request Timeouts (seconds)
# Perplexity 的 SSE 响应总时长在不同模式下差异很大：
#   - auto / pro / reasoning：通常 30~120s
#   - deep research：常见 3~10 分钟，偶尔更久
#
# 真正生效的超时值由 ClientPool 在运行时根据下面的优先级决定：
#   1) admin API /timeouts/config (会持久化进 token_pool_config.json)
#   2) token_pool_config.json 里的 "timeouts" 段
#   3) 环境变量 PPLX_SEARCH_TIMEOUT / PPLX_DEEP_RESEARCH_TIMEOUT / PPLX_FILE_UPLOAD_TIMEOUT
#   4) 这里的内置默认值

# 共享下限：env / json / admin API 三条路径都用同一个守卫，避免一处放行另一处拦截
MIN_TIMEOUT_SECONDS: int = 10


def _read_int_env(name: str, default: int, min_value: int = MIN_TIMEOUT_SECONDS) -> int:
    """
    Read a positive integer from env. Values below `min_value` are rejected and
    fall back to `default` so e.g. `PPLX_SEARCH_TIMEOUT=1` (typo) doesn't make
    every request fail almost immediately.
    """
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _logger.warning("Ignoring %s=%r: not an integer; using default %d", name, raw, default)
        return default
    if value < min_value:
        _logger.warning(
            "Ignoring %s=%d: below minimum %ds; using default %d",
            name,
            value,
            min_value,
            default,
        )
        return default
    return value


# 内置兜底默认（最低优先级）
DEFAULT_SEARCH_TIMEOUT: int = 300
DEFAULT_DEEP_RESEARCH_TIMEOUT: int = 900
DEFAULT_FILE_UPLOAD_TIMEOUT: int = 180

# 环境变量覆盖（用于不依赖 ClientPool 的 fallback 路径，如匿名 Client）
SEARCH_TIMEOUT: int = _read_int_env("PPLX_SEARCH_TIMEOUT", DEFAULT_SEARCH_TIMEOUT)
DEEP_RESEARCH_TIMEOUT: int = _read_int_env(
    "PPLX_DEEP_RESEARCH_TIMEOUT", DEFAULT_DEEP_RESEARCH_TIMEOUT
)
FILE_UPLOAD_TIMEOUT: int = _read_int_env("PPLX_FILE_UPLOAD_TIMEOUT", DEFAULT_FILE_UPLOAD_TIMEOUT)


def get_search_timeout(mode: str) -> int:
    """
    Module-level fallback used when no per-call/per-pool override is provided.
    Higher-priority sources (admin API, token_pool_config.json) are resolved by
    ClientPool.get_search_timeout(mode).
    """
    if mode == "deep research":
        return DEEP_RESEARCH_TIMEOUT
    return SEARCH_TIMEOUT


# Endpoints
ENDPOINT_AUTH_SESSION = f"{API_BASE_URL}/api/auth/session"
ENDPOINT_SSE_ASK = f"{API_BASE_URL}/rest/sse/perplexity_ask"
ENDPOINT_UPLOAD_URL = f"{API_BASE_URL}/rest/uploads/create_upload_url"
ENDPOINT_MODELS_CONFIG = os.getenv(
    "PPLX_MODELS_CONFIG_URL",
    f"{API_BASE_URL}/rest/models/config/v2?version={API_VERSION}&source=default",
)

# The upstream catalog changes independently of this package. Keep a local
# server-side copy and refresh it once a day.
MODEL_CONFIG_CACHE_TTL = _read_int_env(
    "PPLX_MODEL_CACHE_TTL",
    24 * 60 * 60,
    min_value=60,
)

# Search Modes
SEARCH_MODES = ["auto", "pro", "reasoning", "deep research"]
SEARCH_SOURCES = ["web", "scholar", "social"]
SEARCH_LANGUAGES = ["en-US", "en-GB", "pt-BR", "es-ES", "fr-FR", "de-DE", "zh-CN"]

# Model Mappings
MODEL_MAPPINGS: Dict[str, Dict[Optional[str], str]] = {
    "auto": {None: "turbo"},
    "pro": {
        None: "pplx_pro",
        "sonar-2": "experimental",
        # Backward-compatible alias for existing clients.
        "sonar": "experimental",
        "gpt-5.6-terra": "gpt56_terra",
        "claude-sonnet-5": "claude50sonnet",
        "gemini-3.1-pro": "gemini31pro_high",
        "grok-4.5": "grok45low",
    },
    "reasoning": {
        None: "pplx_reasoning",
        "gpt-5.6-terra-thinking": "gpt56_terra_thinking",
        "claude-sonnet-5-thinking": "claude50sonnetthinking",
        "gemini-3.1-pro": "gemini31pro_high",
        "kimi-k3-thinking": "kimik3thinking",
        "glm-5.2": "glm_5_2",
        "grok-4.5-thinking": "grok45medium",
        "nemotron-3-ultra": "nv_nemotron_3_ultra",
    },
    "deep research": {None: "pplx_alpha"},
}

# HTTP Headers Template
DEFAULT_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",  # noqa: E501
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "max-age=0",
    "dnt": "1",
    "priority": "u=0, i",
    "sec-ch-ua": '"Not;A=Brand";v="24", "Chromium";v="128"',
    "sec-ch-ua-arch": '"x86"',
    "sec-ch-ua-bitness": '"64"',
    "sec-ch-ua-full-version": '"128.0.6613.120"',
    "sec-ch-ua-full-version-list": '"Not;A=Brand";v="24.0.0.0", "Chromium";v="128.0.6613.120"',  # noqa: E501
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-model": '""',
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"19.0.0"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",  # noqa: E501
}

# Allowed file extensions for upload (documents, code, images, audio, video)
ALLOWED_FILE_EXTENSIONS: frozenset = frozenset(
    {
        # Documents
        ".pdf",
        ".doc",
        ".docx",
        ".pptx",
        ".xlsx",
        ".csv",
        ".txt",
        ".text",
        ".md",
        ".markdown",
        ".rmd",
        ".latex",
        ".tex",
        # Code & Config
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".cpp",
        ".c",
        ".cxx",
        ".h",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".pl",
        ".pm",
        ".swift",
        ".kt",
        ".kts",
        ".scala",
        ".dart",
        ".lua",
        ".r",
        ".R",
        ".m",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ksh",
        ".bat",
        ".sql",
        ".html",
        ".htm",
        ".css",
        ".less",
        ".xml",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".conf",
        ".config",
        ".in",
        ".log",
        ".coffee",
        ".diff",
        ".ipynb",
        # Images
        ".jpg",
        ".jpeg",
        ".jpe",
        ".jp2",
        ".png",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
        ".svg",
        ".webp",
        ".ico",
        ".avif",
        ".heic",
        ".heif",
        # Audio
        ".mp3",
        ".wav",
        ".aiff",
        ".ogg",
        ".flac",
        # Video
        ".mp4",
        ".mpeg",
        ".mpg",
        ".mov",
        ".avi",
        ".flv",
        ".webm",
        ".wmv",
        ".3gp",
    }
)

# Logging Configuration
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_LEVEL = "DEBUG"
LOG_FILE = "perplexity.log"

# Admin Authentication
# Set this environment variable to enable admin authentication for pool management
# If not set, admin operations will be disabled for security
ADMIN_TOKEN: Optional[str] = os.getenv("PPLX_ADMIN_TOKEN", None)
