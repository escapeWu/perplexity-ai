#!/usr/bin/env python3
"""Fixed-model REST client for the self-hosted escapeWu/perplexity-ai service."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 300.0
ASK_MODEL = "grok-4-6"
RESEARCH_MODEL = "perplexity-deepsearch"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
PLACEHOLDER_KEYS = {"YOUR_MCP_TOKEN", "YOUR_API_KEY", "<MCP_TOKEN>", ""}


class CliError(RuntimeError):
    def __init__(
        self,
        error_type: str,
        message: str,
        *,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.status_code = status_code
        self.details = details


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    timeout_seconds: float


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CliError("config_error", f"Config file not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError("config_error", f"Config file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CliError("config_error", "Config root must be a JSON object")
    return payload


def _normalize_base_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CliError("config_error", "base_url must be a non-empty HTTP(S) URL")
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise CliError("config_error", "base_url must be a plain HTTP(S) service URL")
    return normalized


def _api_url(base_url: str, path: str) -> str:
    prefix = base_url if base_url.endswith("/v1") else f"{base_url}/v1"
    return f"{prefix}/{path.lstrip('/')}"


def load_config(path: Path) -> Config:
    payload = _load_json_file(path)
    base_url = _normalize_base_url(
        os.environ.get("PPLX_BASE_URL")
        or payload.get("base_url")
        or payload.get("baseurl")
        or DEFAULT_BASE_URL
    )
    api_key_value = (
        os.environ.get("MCP_TOKEN")
        or os.environ.get("PPLX_API_KEY")
        or payload.get("api_key")
        or payload.get("apikey")
        or ""
    )
    if not isinstance(api_key_value, str) or api_key_value.strip() in PLACEHOLDER_KEYS:
        raise CliError(
            "config_error",
            "Set MCP_TOKEN or PPLX_API_KEY, or replace the api_key placeholder in config.json",
        )
    timeout_value = payload.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if isinstance(timeout_value, bool) or not isinstance(timeout_value, (int, float)):
        raise CliError("config_error", "timeout_seconds must be a number")
    timeout_seconds = float(timeout_value)
    if not 1 <= timeout_seconds <= 1800:
        raise CliError("config_error", "timeout_seconds must be between 1 and 1800")
    return Config(
        base_url=base_url,
        api_key=api_key_value.strip(),
        timeout_seconds=timeout_seconds,
    )


def _decode_json(data: bytes, *, error_type: str, message: str) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CliError(error_type, message) from exc
    if not isinstance(payload, dict):
        raise CliError(error_type, message)
    return payload


def request_json(config: Config, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        _api_url(config.base_url, "chat/completions"),
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
        details: Any
        try:
            details = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            details = raw.decode("utf-8", errors="replace")[:2000]
        message = f"Perplexity service returned HTTP {exc.code}"
        if isinstance(details, dict):
            upstream_error = details.get("error")
            if isinstance(upstream_error, dict) and isinstance(
                upstream_error.get("message"), str
            ):
                message = upstream_error["message"]
        raise CliError("api_error", message, status_code=exc.code, details=details) from exc
    except URLError as exc:
        reason = str(exc.reason) if exc.reason else "connection failed"
        raise CliError("connection_error", f"Could not reach Perplexity service: {reason}") from exc
    except TimeoutError as exc:
        raise CliError("timeout", "Perplexity service request timed out") from exc

    if len(raw) > MAX_RESPONSE_BYTES:
        raise CliError("response_too_large", "Perplexity response exceeded 16 MiB")
    return _decode_json(
        raw,
        error_type="invalid_response",
        message="Perplexity service returned invalid JSON",
    )


def _message_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise CliError("invalid_response", "Response does not contain choices[0]")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise CliError("invalid_response", "Response does not contain choices[0].message")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text", item.get("content"))
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "\n".join(parts)
    raise CliError("invalid_response", "Response message does not contain text content")


def run_chat(
    config: Config,
    *,
    query: str,
    model: str,
    thinking: bool | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise CliError("invalid_request", "query must not be empty")
    request_payload: dict[str, Any] = {
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": query}],
    }
    if thinking is not None:
        request_payload["thinking"] = thinking
    if session_id is not None:
        session_id = session_id.strip()
        if not session_id:
            raise CliError("invalid_request", "session_id must not be empty")
        request_payload["session_id"] = session_id

    payload = request_json(config, request_payload)
    return {
        "status": "ok",
        "session_id": payload.get("session_id"),
        "model": payload.get("model", model),
        "answer": _message_text(payload),
        "sources": payload.get("sources", []),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Call fixed Grok 4.6 Ask or Perplexity Deep Research routing"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help=f"config file (default: {CONFIG_PATH})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask = subparsers.add_parser("ask", help="search with fixed model grok-4-6")
    ask.add_argument("query", help="latest user question or follow-up")
    ask.add_argument(
        "--thinking",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="enable Grok thinking (default: enabled)",
    )
    ask.add_argument("--session-id", help="continue an existing Ask session")

    research = subparsers.add_parser(
        "research", help="research with fixed model perplexity-deepsearch"
    )
    research.add_argument("query", help="latest user question or follow-up")
    research.add_argument("--session-id", help="continue an existing Research session")
    return parser


def _print_json(payload: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    json.dump(payload, stream, ensure_ascii=False, indent=2)
    stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        model = ASK_MODEL if args.command == "ask" else RESEARCH_MODEL
        thinking = args.thinking if args.command == "ask" else None
        result = run_chat(
            config,
            query=args.query,
            model=model,
            thinking=thinking,
            session_id=args.session_id,
        )
    except CliError as exc:
        error: dict[str, Any] = {
            "status": "error",
            "error_type": exc.error_type,
            "message": exc.message,
        }
        if exc.status_code is not None:
            error["status_code"] = exc.status_code
        _print_json(error, stream=sys.stderr)
        return 1

    _print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
