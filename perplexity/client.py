"""Synchronous Python client and shared Perplexity browser request contract."""
from __future__ import annotations

import logging
import mimetypes
import re
import threading
from http.cookiejar import Cookie
from uuid import uuid4

from curl_cffi import CurlMime, requests

from .config import (
    DEFAULT_HEADERS, ENDPOINT_AUTH_SESSION, ENDPOINT_SSE_ASK, ENDPOINT_UPLOAD_URL,
    FILE_UPLOAD_TIMEOUT, SOCKS_PROXY, get_search_timeout,
)
from .model_registry import get_model_registry, normalize_subscription_tier
from .upstream_protocol import ResponseState, SSEDecoder, UpstreamError, check_response, check_http_status

logger = logging.getLogger(__name__)


def _normalize_follow_up(follow_up):
    if follow_up is None:
        return None, []
    if not isinstance(follow_up, dict):
        raise ValueError("follow_up must be an object")
    backend = follow_up.get("backend_uuid")
    attachments = follow_up.get("attachments", [])
    if not isinstance(backend, str) or not backend.strip():
        raise ValueError("follow_up.backend_uuid must be a non-empty string")
    if not isinstance(attachments, list) or not all(isinstance(x, str) for x in attachments):
        raise ValueError("follow_up.attachments must be a list of strings")
    return backend.strip(), list(attachments)


def annotate_model_downgrade(response: dict, requested_internal_id: str | None) -> bool:
    selected, effective = response.get("user_selected_model"), response.get("display_model")
    if not requested_internal_id or selected != requested_internal_id or not effective or effective == requested_internal_id:
        return False
    response.update(model_downgraded=True, requested_model=requested_internal_id,
                    effective_model=effective)
    return True


class Client:
    def __init__(self, cookies=None):
        self._cookies = dict(cookies or {})
        self._cookie_lock = threading.RLock()
        self._cookie_generation = 0
        self.session = requests.Session(headers=DEFAULT_HEADERS.copy(), cookies=scoped_cookies(self._cookies),
                                        impersonate="chrome", proxy=SOCKS_PROXY.split("#")[0] if SOCKS_PROXY else None)
        self.own = bool(cookies)
        self.copilot = float("inf") if cookies else 0
        self.file_upload = float("inf") if cookies else 0
        self._user_info = {}
        self.subscription_tier = normalize_subscription_tier(None, own_account=self.own)
        try:
            response = self._probe_session()
            if response is not None and response.ok:
                self._update_user_info(response.json())
        except Exception:
            logger.debug("Account metadata was unavailable during initialization")

    def account_hint(self) -> str:
        # Perplexity's session middleware selects the account via the
        # x-pplx-account header; the id is recoverable from our own cookies.
        hint = self._cookies.get("__Host-pplx-last-active-account")
        if not hint:
            for name in self._cookies:
                if name.startswith("__Secure-pplx.session."):
                    hint = name[len("__Secure-pplx.session."):]
                    break
        return hint or ""

    def _probe_session(self):
        hint = self.account_hint()
        headers = {"x-pplx-account": hint} if hint else {}
        return self.session.get(ENDPOINT_AUTH_SESSION, headers=headers, timeout=30)

    @property
    def cookies(self) -> dict:
        if hasattr(self.session, "cookies") and hasattr(self.session.cookies, "get_dict"):
            return self.session.cookies.get_dict()
        return self._cookies.copy()

    def cookie_snapshot(self):
        with self._cookie_lock:
            return self._cookie_generation, self.cookies

    def merge_cookies(self, generation, original, updated):
        # Only compare-and-set changed values. A stale request cannot overwrite a newer cookie.
        with self._cookie_lock:
            current = self.cookies
            changed = False
            for name, value in updated.items():
                if value != original.get(name) and current.get(name) == original.get(name):
                    self.session.cookies.delete(name)
                    set_account_cookie(self.session.cookies, name, value)
                    changed = True
            if changed:
                self._cookie_generation += 1
                self._cookies = self.cookies

    def get_user_info(self) -> dict:
        try:
            response = self._probe_session()
            if response.ok:
                data = response.json()
                self._update_user_info(data)
                return data
        except Exception:
            pass
        return {}

    def _update_user_info(self, user_info):
        if not isinstance(user_info, dict):
            return
        self._user_info = user_info
        user = user_info.get("user")
        tier = user.get("subscription_tier") if isinstance(user, dict) else user_info.get("subscription_tier")
        self.subscription_tier = normalize_subscription_tier(tier, own_account=self.own)

    def _search_request_headers(self, frontend_uuid: str, language: str) -> dict:
        language = str(language or "en-US")
        base = language.split("-", 1)[0]
        origin = ENDPOINT_SSE_ASK.split("/rest/", 1)[0]
        headers = {
            "accept": "text/event-stream", "accept-language": f"{language},{base};q=0.9,en;q=0.8" if base != "en" else f"{language},en;q=0.9",
            "cache-control": "no-cache", "content-type": "application/json", "origin": origin,
            "pragma": "no-cache", "priority": "u=1, i", "referer": f"{origin}/",
            "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin",
            "x-perplexity-request-endpoint": ENDPOINT_SSE_ASK,
            "x-perplexity-request-reason": "ask-query-state-provider", "x-perplexity-request-try-number": "1",
            "x-request-id": frontend_uuid,
        }
        info = getattr(self, "_user_info", {})
        user = info.get("user") if isinstance(info, dict) else None
        if isinstance(user, dict) and user.get("id"):
            headers["x-pplx-account"] = str(user["id"])
        return headers

    def prepare_search(self, query, mode="auto", model=None, sources=None, language="en-US",
                       follow_up=None, incognito=False, uploaded_files=None):
        assert mode in ("auto", "pro", "reasoning", "deep research"), "Invalid search mode."
        sources = ["web"] if sources is None else sources
        assert all(x in ("web", "scholar", "social") for x in sources), "Invalid sources."
        tier = getattr(self, "subscription_tier", normalize_subscription_tier(None, own_account=self.own))
        try:
            definition = get_model_registry().resolve(mode, model, account_tier=tier)
        except ValueError as exc:
            raise AssertionError(str(exc)) from exc
        assert mode == "auto" or self.copilot > 0, "No remaining pro queries."
        backend, prior_files = _normalize_follow_up(follow_up)
        frontend = str(uuid4())
        payload = {"query_str": query, "params": {
            "attachments": list(uploaded_files or []) + prior_files,
            "frontend_context_uuid": str(uuid4()), "frontend_uuid": frontend,
            "is_incognito": incognito, "language": language, "last_backend_uuid": backend,
            "mode": "concise" if mode == "auto" else "copilot",
            "model_preference": definition.internal_id,
            "query_source": "followup" if backend else "home", "source": "default",
            "sources": sources, "version": "2.18",
        }}
        return payload, self._search_request_headers(frontend, language)

    def search(self, query, mode="auto", model=None, sources=None, files=None, stream=False,
               language="en-US", follow_up=None, incognito=False, timeout=None,
               file_upload_timeout=None):
        files = files or {}
        # Validate before any upload side effects.
        self.prepare_search(query, mode, model, sources, language, follow_up, incognito)
        assert self.file_upload >= len(files), "File upload limit exceeded."
        uploaded = []
        for filename, content in files.items():
            file_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            response = self.session.post(ENDPOINT_UPLOAD_URL, params={"version": "2.18", "source": "default"},
                json={"content_type": file_type, "file_size": len(content), "filename": filename,
                      "force_image": False, "source": "default"}, timeout=30)
            check_http_status(response.status_code, response.headers)
            info = response.json()
            multipart = CurlMime()
            try:
                for key, value in info["fields"].items():
                    multipart.addpart(name=key, data=value)
                multipart.addpart(name="file", content_type=file_type, filename=filename, data=content)
                result = self.session.post(info["s3_bucket_url"], multipart=multipart,
                                           timeout=file_upload_timeout or FILE_UPLOAD_TIMEOUT)
                check_http_status(result.status_code, result.headers)
                uploaded.append(uploaded_file_url(info, result))
            finally:
                multipart.close()
        payload, headers = self.prepare_search(query, mode, model, sources, language, follow_up, incognito, uploaded)
        if mode != "auto":
            self.copilot -= 1
        self.file_upload -= len(files)

        def consume():
            warned = False
            state = ResponseState(payload["params"]["attachments"])
            response = self.session.post(ENDPOINT_SSE_ASK, json=payload, headers=headers,
                                         stream=True, timeout=timeout or get_search_timeout(mode))
            try:
                check_response(response.status_code, response.headers)
                # iter_lines supplies SSE frames on the synchronous compatibility API.
                for frame in response.iter_lines(delimiter=b"\n"):
                    for event, text in decoder.feed(frame + b"\n"):
                        chunk = state.feed(event, text)
                        if chunk is not None:
                            downgraded = annotate_model_downgrade(chunk, payload["params"]["model_preference"] if model else None)
                            if downgraded and not warned:
                                logger.warning("Upstream silently downgraded the requested model")
                                warned = True
                            yield chunk
                        if state.ended:
                            state.finish()
                            return
                state.finish()
            finally:
                response.close()

        decoder = SSEDecoder()
        if stream:
            return consume()
        latest = None
        for latest in consume():
            pass
        if latest is None:
            raise UpstreamError("Upstream completed without an answer", "empty_answer")
        return latest

    def close(self):
        self.session.close()


def set_account_cookie(jar, name, value):
    # Response cookies may use a parent domain. Remove duplicate names before a
    # scoped replacement so an older domain entry cannot win get_dict().
    jar.delete(name)
    jar.jar.set_cookie(Cookie(version=0, name=name, value=value, port=None, port_specified=False,
        domain="www.perplexity.ai", domain_specified=False, domain_initial_dot=False,
        path="/", path_specified=True, secure=True, expires=None, discard=True,
        comment=None, comment_url=None, rest={"HttpOnly": None}))


def scoped_cookies(values):
    """Host-only account cookies must never reach S3/Cloudinary upload requests."""
    jar = requests.Cookies()
    for name, value in values.items():
        set_account_cookie(jar, name, value)
    return jar


def uploaded_file_url(info, response):
    if "image/upload" in info["s3_object_url"]:
        return re.sub(r"/private/s--.*?--/v\d+/user_uploads/", "/private/user_uploads/", response.json()["secure_url"])
    return info["s3_object_url"]
