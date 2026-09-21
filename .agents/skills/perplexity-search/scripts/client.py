#!/usr/bin/env python3
"""REST client with the same call surface as the Perplexity MCP v2 tools."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 300.0
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
PLACEHOLDER_KEYS = {"YOUR_MCP_TOKEN", "YOUR_API_KEY", "<MCP_TOKEN>", ""}
Files = Mapping[str, bytes | str] | Iterable[str | os.PathLike[str]] | None


class ClientError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    timeout_seconds: float


def _error(error_type: str, message: str, **details: Any) -> dict[str, Any]:
    return {"status": "error", "error_type": error_type, "message": message, **details}


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ClientError("config_error", f"Config file not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ClientError("config_error", f"Config file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ClientError("config_error", "Config root must be a JSON object")
    return payload


def _normalize_base_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClientError("config_error", "base_url must be a non-empty HTTP(S) URL")
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
        raise ClientError("config_error", "base_url must be a plain HTTP(S) service URL")
    return normalized[:-3] if normalized.endswith("/v1") else normalized


def load_config(path: Path = CONFIG_PATH) -> Config:
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
        raise ClientError(
            "config_error",
            "Set MCP_TOKEN or PPLX_API_KEY, or replace the api_key placeholder in config.json",
        )
    timeout_value = payload.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if isinstance(timeout_value, bool) or not isinstance(timeout_value, (int, float)):
        raise ClientError("config_error", "timeout_seconds must be a number")
    timeout_seconds = float(timeout_value)
    if not 1 <= timeout_seconds <= 1800:
        raise ClientError("config_error", "timeout_seconds must be between 1 and 1800")
    return Config(base_url, api_key_value.strip(), timeout_seconds)


def _decode_json(data: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientError("invalid_response", "Perplexity service returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ClientError("invalid_response", "Perplexity service returned a non-object response")
    return payload


def _message_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ClientError("invalid_response", "Response does not contain choices[0]")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ClientError("invalid_response", "Response message does not contain text content")
    return message["content"]


def _file_items(files: Files) -> list[tuple[str, bytes]]:
    if files is None:
        return []
    if isinstance(files, Mapping):
        items = []
        for name, data in files.items():
            if not isinstance(name, str) or not name:
                raise ClientError("ValidationError", "file names must be non-empty strings")
            if isinstance(data, str):
                data = data.encode()
            if not isinstance(data, bytes):
                raise ClientError("ValidationError", "file values must be bytes or text")
            items.append((Path(name).name, data))
        return items
    if isinstance(files, (str, bytes)):
        raise ClientError("ValidationError", "files must be an object or an iterable of paths")
    items = []
    try:
        for value in files:
            path = Path(value).expanduser()
            items.append((path.name, path.read_bytes()))
    except (OSError, TypeError, ValueError) as exc:
        raise ClientError("ValidationError", f"Unable to read attachment: {exc}") from exc
    return items


def _user_content(query: str, files: Files) -> str | list[dict[str, str]]:
    items = _file_items(files)
    if not items:
        return query
    content: list[dict[str, str]] = [{"type": "text", "text": query}]
    for name, data in items:
        encoded = base64.b64encode(data).decode("ascii")
        content.append(
            {
                "type": "input_file",
                "filename": name,
                "file_data": f"data:application/octet-stream;base64,{encoded}",
            }
        )
    return content


class PerplexityRestClient:
    """Python REST adapter matching the public MCP v2 tool methods."""

    def __init__(self, base_url: str, api_key: str, timeout_seconds: float = 300.0) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_config(cls, path: Path = CONFIG_PATH) -> "PerplexityRestClient":
        config = load_config(path)
        return cls(config.base_url, config.api_key, config.timeout_seconds)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/v1/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            **(headers or {}),
        }
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(url, data=data, method=method, headers=request_headers)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
            try:
                details = _decode_json(raw)
            except ClientError:
                details = {}
            api_error = details.get("error", {}) if isinstance(details, dict) else {}
            if not isinstance(api_error, dict):
                api_error = {}
            error_type = api_error.get("type", "api_error")
            if error_type == "invalid_request_error":
                error_type = (
                    "SessionNotFound"
                    if exc.code == 404 and details.get("session_id")
                    else "ValidationError"
                )
            extra = {
                key: value for key, value in api_error.items() if key not in {"type", "message"}
            }
            result = _error(
                error_type,
                api_error.get("message", f"Perplexity service returned HTTP {exc.code}"),
                status_code=exc.code,
                **extra,
            )
            if isinstance(details, dict) and details.get("session_id") is not None:
                result["session_id"] = details["session_id"]
            return result
        except URLError as exc:
            reason = str(exc.reason) if exc.reason else "connection failed"
            return _error("connection_error", f"Could not reach Perplexity service: {reason}")
        except TimeoutError:
            return _error("timeout", "Perplexity service request timed out")
        if len(raw) > MAX_RESPONSE_BYTES:
            return _error("response_too_large", "Perplexity response exceeded 16 MiB")
        try:
            return _decode_json(raw)
        except ClientError as exc:
            return _error(exc.error_type, exc.message)

    def _complete(
        self,
        query: str,
        *,
        model: str,
        thinking: bool,
        session_id: str | None,
        files: Files,
    ) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return _error("ValidationError", "query must be a non-empty string")
        try:
            content = _user_content(query.strip(), files)
        except ClientError as exc:
            return _error(exc.error_type, exc.message)
        payload: dict[str, Any] = {
            "model": model,
            "thinking": thinking,
            "stream": False,
            "messages": [{"role": "user", "content": content}],
        }
        if session_id is not None:
            payload["session_id"] = session_id
        response = self._request_json("POST", "chat/completions", payload=payload)
        if response.get("status") == "error":
            return response
        try:
            data = {
                "answer": _message_text(response),
                "sources": response.get("sources", []),
            }
        except ClientError as exc:
            return _error(exc.error_type, exc.message)
        return {
            "status": "ok",
            "session_id": response.get("session_id"),
            "job_id": response.get("job_id"),
            "model": response.get("model", model),
            "data": data,
        }

    def perplexity_ask_v2(
        self,
        query: str,
        model: str | None = None,
        thinking: bool = False,
        session_id: str | None = None,
        files: Files = None,
    ) -> dict[str, Any]:
        """Match the MCP perplexity_ask_v2 contract over REST."""
        if not isinstance(thinking, bool):
            return _error("ValidationError", "thinking must be a boolean")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            return _error("ValidationError", "model must be a non-empty OAI model ID")
        requested_model = model or "perplexity-search"
        if requested_model == "perplexity-deepsearch":
            return _error(
                "ValidationError",
                "perplexity_ask_v2 does not accept the Deep Research model; "
                "use perplexity_research_v2",
            )
        return self._complete(
            query,
            model=requested_model,
            thinking=thinking,
            session_id=session_id,
            files=files,
        )

    def perplexity_research_v2(
        self,
        query: str,
        session_id: str | None = None,
        files: Files = None,
    ) -> dict[str, Any]:
        """Match the MCP perplexity_research_v2 contract over REST."""
        return self._complete(
            query,
            model="perplexity-deepsearch",
            thinking=False,
            session_id=session_id,
            files=files,
        )

    def perplexity_task_submit(
        self,
        query: str,
        model: str = "perplexity-search",
        thinking: bool = False,
        session_id: str | None = None,
        files: Files = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Match the MCP detached task submission contract over REST."""
        if not isinstance(query, str) or not query.strip():
            return _error("ValidationError", "query must be a non-empty string")
        try:
            content = _user_content(query.strip(), files)
        except ClientError as exc:
            return _error(exc.error_type, exc.message)
        payload: dict[str, Any] = {
            "model": model,
            "thinking": thinking,
            "messages": [{"role": "user", "content": content}],
        }
        if session_id is not None:
            payload["session_id"] = session_id
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        response = self._request_json("POST", "jobs", payload=payload, headers=headers)
        return response if response.get("status") == "error" else {"status": "ok", **response}

    def perplexity_task_status(
        self,
        job_id: str,
        wait_seconds: float = 0,
        include_output: bool = True,
    ) -> dict[str, Any]:
        """Match the MCP detached task status contract over REST."""
        if not isinstance(job_id, str) or not job_id:
            return _error("ValidationError", "job_id must be a non-empty string")
        if not isinstance(wait_seconds, (int, float)) or not 0 <= wait_seconds <= 30:
            return _error("ValidationError", "wait_seconds must be between 0 and 30")
        if wait_seconds:
            response = self._request_json(
                "GET",
                f"jobs/{job_id}/result",
                params={"wait_seconds": wait_seconds},
            )
            if response.get("status") == "error":
                response = self._request_json(
                    "GET",
                    f"jobs/{job_id}",
                    params={"include_output": str(include_output).lower()},
                )
        else:
            response = self._request_json(
                "GET",
                f"jobs/{job_id}",
                params={"include_output": str(include_output).lower()},
            )
        if response.get("status") == "error":
            return response
        result = dict(response)
        snapshot = result.pop("result", None)
        if include_output and snapshot is not None:
            result["snapshot"] = snapshot
        if not include_output:
            result.pop("snapshot", None)
        return {"status": "ok", **result}

    def perplexity_task_cancel(self, job_id: str) -> dict[str, Any]:
        """Match the MCP detached task cancellation contract over REST."""
        if not isinstance(job_id, str) or not job_id:
            return _error("ValidationError", "job_id must be a non-empty string")
        response = self._request_json("POST", f"jobs/{job_id}/cancel")
        return response if response.get("status") == "error" else {"status": "ok", **response}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call Perplexity REST with MCP v2 tool semantics")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    commands = parser.add_subparsers(dest="command", required=True)

    ask = commands.add_parser("perplexity_ask_v2")
    ask.add_argument("query")
    ask.add_argument("--model")
    ask.add_argument("--thinking", action="store_true")
    ask.add_argument("--session-id")
    ask.add_argument("--file", action="append", default=[])

    research = commands.add_parser("perplexity_research_v2")
    research.add_argument("query")
    research.add_argument("--session-id")
    research.add_argument("--file", action="append", default=[])

    submit = commands.add_parser("perplexity_task_submit")
    submit.add_argument("query")
    submit.add_argument("--model", default="perplexity-search")
    submit.add_argument("--thinking", action="store_true")
    submit.add_argument("--session-id")
    submit.add_argument("--file", action="append", default=[])
    submit.add_argument("--idempotency-key")

    status = commands.add_parser("perplexity_task_status")
    status.add_argument("job_id")
    status.add_argument("--wait-seconds", type=float, default=0)
    status.add_argument("--no-output", action="store_true")

    cancel = commands.add_parser("perplexity_task_cancel")
    cancel.add_argument("job_id")
    return parser


def _dispatch(client: PerplexityRestClient, args: argparse.Namespace) -> dict[str, Any]:
    method: Callable[..., dict[str, Any]] = getattr(client, args.command)
    if args.command == "perplexity_ask_v2":
        return method(args.query, args.model, args.thinking, args.session_id, args.file or None)
    if args.command == "perplexity_research_v2":
        return method(args.query, args.session_id, args.file or None)
    if args.command == "perplexity_task_submit":
        return method(
            args.query,
            args.model,
            args.thinking,
            args.session_id,
            args.file or None,
            args.idempotency_key,
        )
    if args.command == "perplexity_task_status":
        return method(args.job_id, args.wait_seconds, not args.no_output)
    return method(args.job_id)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = PerplexityRestClient.from_config(args.config)
        result = _dispatch(client, args)
    except ClientError as exc:
        result = _error(exc.error_type, exc.message)
    output = sys.stdout if result["status"] == "ok" else sys.stderr
    json.dump(result, output, ensure_ascii=False, indent=2)
    output.write("\n")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
