# Importing necessary modules
# re: Regular expressions for pattern matching
# sys: System-specific parameters and functions
# json: JSON parsing and serialization
# mimetypes: Guessing MIME types of files
# uuid: Generating unique identifiers
# curl_cffi: HTTP requests and multipart form data handling
import json
import logging
import mimetypes
import re
import sys
from uuid import uuid4

# Try importing curl_cffi, but allow it to fail for testing environments
# that mock the requests anyway
try:
    from curl_cffi import CurlMime, requests
except ImportError:
    # Minimal stub for testing if curl_cffi is missing
    class requests:
        class Session:
            def __init__(self, *args, **kwargs):
                pass

            def get(self, *args, **kwargs):
                pass

            def post(self, *args, **kwargs):
                pass

    class CurlMime:
        def __init__(self, *args, **kwargs):
            pass

        def addpart(self, *args, **kwargs):
            pass


from .config import (
    DEFAULT_HEADERS,
    ENDPOINT_AUTH_SESSION,
    ENDPOINT_SSE_ASK,
    ENDPOINT_UPLOAD_URL,
    FILE_UPLOAD_TIMEOUT,
    SOCKS_PROXY,
    get_search_timeout,
)
from .model_registry import get_model_registry, normalize_subscription_tier
from .response_parser import UpstreamResponseAccumulator

logger = logging.getLogger(__name__)


def annotate_model_downgrade(
    response: dict,
    requested_internal_id: str | None,
) -> bool:
    """Mark an upstream response when Perplexity silently changes the model."""
    if not requested_internal_id:
        return False

    selected_model = response.get("user_selected_model")
    effective_model = response.get("display_model")
    if (
        selected_model != requested_internal_id
        or not effective_model
        or effective_model == requested_internal_id
    ):
        return False

    response["model_downgraded"] = True
    response["requested_model"] = requested_internal_id
    response["effective_model"] = effective_model
    return True


class Client:
    """
    A client for interacting with the Perplexity AI API.
    """

    def __init__(self, cookies={}):
        # Build proxy configuration from SOCKS_PROXY env var
        # Format: socks5://[user[:pass]@]host[:port][#remark]
        proxy_url = None
        if SOCKS_PROXY:
            # Remove the remark part (after #) if present
            proxy_url = SOCKS_PROXY.split("#")[0] if "#" in SOCKS_PROXY else SOCKS_PROXY
            logger.debug("Client proxy configured: %s", proxy_url.split("@")[-1])
        else:
            logger.debug("Client proxy not configured, using direct connection")

        # Store original cookies for export
        self._cookies = cookies.copy() if cookies else {}

        # Initialize an HTTP session with default headers and optional cookies
        self.session = requests.Session(
            headers=DEFAULT_HEADERS.copy(),
            cookies=cookies,
            impersonate="chrome",
            proxy=proxy_url,
        )
        logger.debug(
            "Client session initialized (impersonate=chrome, proxy=%s)",
            "enabled" if proxy_url else "disabled",
        )

        # Flags and counters for account and query management
        self.own = bool(cookies)  # Indicates if the client uses its own account
        self.copilot = 0 if not cookies else float("inf")  # Remaining pro queries
        self.file_upload = 0 if not cookies else float("inf")  # Remaining file uploads
        self._user_info = {}
        self.subscription_tier = normalize_subscription_tier(None, own_account=self.own)

        # Initialize session by making a GET request
        logger.debug("Client initializing auth session via %s", ENDPOINT_AUTH_SESSION)
        try:
            response = self.session.get(ENDPOINT_AUTH_SESSION, timeout=30)
            if response is not None and response.ok:
                self._update_user_info(response.json())
        except Exception as exc:
            logger.debug("Unable to read account tier during initialization: %s", exc)

    @property
    def cookies(self) -> dict:
        """
        Get the current cookies from the session.
        """
        if hasattr(self.session, "cookies") and hasattr(self.session.cookies, "get_dict"):
            return self.session.cookies.get_dict()
        return self._cookies

    def get_user_info(self) -> dict:
        """
        Get user session information from the auth session endpoint.

        Returns:
            dict: User session info including user details if logged in,
                  or empty dict if anonymous/not logged in.
        """
        try:
            resp = self.session.get(ENDPOINT_AUTH_SESSION, timeout=30)
            if resp.ok:
                user_info = resp.json()
                self._update_user_info(user_info)
                return user_info
            return {}
        except Exception:
            return {}

    def _update_user_info(self, user_info) -> None:
        """Cache session metadata and the tier used by pool routing."""
        if not isinstance(user_info, dict):
            return
        self._user_info = user_info
        user = user_info.get("user")
        raw_tier = (
            user.get("subscription_tier")
            if isinstance(user, dict)
            else user_info.get("subscription_tier")
        )
        self.subscription_tier = normalize_subscription_tier(raw_tier, own_account=self.own)

    def _search_request_headers(self, frontend_uuid: str, language: str) -> dict:
        """Build the browser protocol headers used by Perplexity's ask endpoint."""
        language = str(language or "en-US")
        base_language = language.split("-", 1)[0]
        api_origin = ENDPOINT_SSE_ASK.split("/rest/", 1)[0]
        accept_language = (
            f"{language},{base_language};q=0.9,en;q=0.8"
            if base_language != "en"
            else f"{language},en;q=0.9"
        )
        headers = {
            "accept": "text/event-stream",
            "accept-language": accept_language,
            "cache-control": "no-cache",
            "content-type": "application/json",
            "origin": api_origin,
            "pragma": "no-cache",
            "priority": "u=1, i",
            "referer": f"{api_origin}/",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-perplexity-request-endpoint": ENDPOINT_SSE_ASK,
            "x-perplexity-request-reason": "ask-query-state-provider",
            "x-perplexity-request-try-number": "1",
            # The web client correlates this header with params.frontend_uuid.
            "x-request-id": frontend_uuid,
        }

        user_info = getattr(self, "_user_info", {})
        user = user_info.get("user") if isinstance(user_info, dict) else None
        account_id = user.get("id") if isinstance(user, dict) else None
        if account_id:
            # Perplexity uses this account context when checking access to an
            # explicitly selected Pro/Max model.
            headers["x-pplx-account"] = str(account_id)

        return headers

    def search(
        self,
        query,
        mode="auto",
        model=None,
        sources=["web"],
        files={},
        stream=False,
        language="en-US",
        follow_up=None,
        incognito=False,
        timeout=None,
        file_upload_timeout=None,
    ):
        """
        Executes a search query on Perplexity AI.

        Parameters:
        - query: The search query string.
        - mode: Search mode ('auto', 'pro', 'reasoning', 'deep research').
        - model: Specific model to use for the query.
        - sources: List of sources ('web', 'scholar', 'social').
        - files: Dictionary of files to upload.
        - stream: Whether to stream the response.
        - language: Language code (ISO 639).
        - follow_up: Information for follow-up queries.
        - incognito: Whether to enable incognito mode.
        """
        # Validate input parameters
        assert mode in [
            "auto",
            "pro",
            "reasoning",
            "deep research",
        ], "Invalid search mode."
        account_tier = getattr(
            self,
            "subscription_tier",
            normalize_subscription_tier(None, own_account=self.own),
        )
        try:
            model_definition = get_model_registry().resolve(
                mode,
                model,
                account_tier=account_tier,
            )
        except ValueError as exc:
            raise AssertionError(str(exc)) from exc
        assert all(
            [source in ("web", "scholar", "social") for source in sources]
        ), "Invalid sources."
        assert (
            self.copilot > 0 if mode in ["pro", "reasoning", "deep research"] else True
        ), "No remaining pro queries."
        assert self.file_upload - len(files) >= 0 if files else True, "File upload limit exceeded."

        # Update query and file upload counters
        self.copilot = (
            self.copilot - 1 if mode in ["pro", "reasoning", "deep research"] else self.copilot
        )
        self.file_upload = self.file_upload - len(files) if files else self.file_upload

        # Upload files and prepare the query payload
        uploaded_files = []
        for filename, file in files.items():
            file_type = mimetypes.guess_type(filename)[0]
            file_upload_info = (
                self.session.post(
                    ENDPOINT_UPLOAD_URL,
                    params={"version": "2.18", "source": "default"},
                    json={
                        "content_type": file_type,
                        "file_size": sys.getsizeof(file),
                        "filename": filename,
                        "force_image": False,
                        "source": "default",
                    },
                    timeout=30,
                )
            ).json()

            # Upload the file to the server
            mp = CurlMime()
            for key, value in file_upload_info["fields"].items():
                mp.addpart(name=key, data=value)
            mp.addpart(
                name="file",
                content_type=file_type,
                filename=filename,
                data=file,
            )

            upload_timeout = (
                file_upload_timeout
                if file_upload_timeout and file_upload_timeout > 0
                else FILE_UPLOAD_TIMEOUT
            )
            upload_resp = self.session.post(
                file_upload_info["s3_bucket_url"], multipart=mp, timeout=upload_timeout
            )

            if not upload_resp.ok:
                raise Exception("File upload error", upload_resp)

            # Extract the uploaded file URL
            if "image/upload" in file_upload_info["s3_object_url"]:
                uploaded_url = re.sub(
                    r"/private/s--.*?--/v\\d+/user_uploads/",
                    "/private/user_uploads/",
                    upload_resp.json()["secure_url"],
                )
            else:
                uploaded_url = file_upload_info["s3_object_url"]

            uploaded_files.append(uploaded_url)

        # Prepare the JSON payload for the query
        frontend_context_uuid = str(uuid4())
        frontend_uuid = str(uuid4())
        json_data = {
            "query_str": query,
            "params": {
                "attachments": (
                    uploaded_files + follow_up["attachments"] if follow_up else uploaded_files
                ),
                "frontend_context_uuid": frontend_context_uuid,
                "frontend_uuid": frontend_uuid,
                "is_incognito": incognito,
                "language": language,
                "last_backend_uuid": (follow_up["backend_uuid"] if follow_up else None),
                "mode": "concise" if mode == "auto" else "copilot",
                "model_preference": model_definition.internal_id,
                "query_source": "followup" if follow_up else "home",
                "source": "default",
                "sources": sources,
                "version": "2.18",
            },
        }

        # Send the query request and handle the response
        # 不同模式耗时差异巨大（deep research 经常需要数分钟）。
        # 优先使用调用方显式传入的 timeout（由 ClientPool 注入），否则按 mode 兜底。
        request_timeout = timeout if timeout and timeout > 0 else get_search_timeout(mode)
        chunks = []
        response_accumulator = UpstreamResponseAccumulator()
        requested_internal_id = model_definition.internal_id if model is not None else None
        downgrade_reported = False

        def open_response():
            return self.session.post(
                ENDPOINT_SSE_ASK,
                json=json_data,
                headers=self._search_request_headers(frontend_uuid, language),
                stream=True,
                timeout=request_timeout,
            )

        def stream_response(resp=None):
            """
            Generator for streaming responses.
            """
            nonlocal downgrade_reported
            if resp is None:
                # Defer opening streaming connections until the caller starts
                # consuming the generator, avoiding leaks for unused streams.
                resp = open_response()
            try:
                for chunk in resp.iter_lines(delimiter=b"\r\n\r\n"):
                    content = chunk.decode("utf-8")

                    if content.startswith("event: message\r\n"):
                        try:
                            content_json = json.loads(content[len("event: message\r\ndata: ") :])

                            # Parse the nested 'text' field if it exists
                            if "text" in content_json and content_json["text"]:
                                try:
                                    text_parsed = json.loads(content_json["text"])
                                    # Extract answer from FINAL step if available
                                    if isinstance(text_parsed, list):
                                        for step in text_parsed:
                                            if step.get("step_type") == "FINAL":
                                                final_content = step.get("content", {})
                                                if "answer" in final_content:
                                                    answer_data = json.loads(
                                                        final_content["answer"]
                                                    )
                                                    content_json["answer"] = answer_data.get(
                                                        "answer", ""
                                                    )
                                                    content_json["chunks"] = answer_data.get(
                                                        "chunks", []
                                                    )
                                                    break
                                    content_json["text"] = text_parsed
                                except (json.JSONDecodeError, TypeError, KeyError):
                                    pass

                            content_json = response_accumulator.normalize(content_json)

                            if (
                                annotate_model_downgrade(
                                    content_json,
                                    requested_internal_id,
                                )
                                and not downgrade_reported
                            ):
                                logger.warning(
                                    "Perplexity silently downgraded the selected model: "
                                    "requested=%s effective=%s status=%s",
                                    requested_internal_id,
                                    content_json.get("effective_model"),
                                    content_json.get("status"),
                                )
                                downgrade_reported = True

                            chunks.append(content_json)
                            yield chunks[-1]
                        except (json.JSONDecodeError, KeyError):
                            continue

                    elif content.startswith("event: end_of_stream\r\n"):
                        return
            finally:
                resp.close()

        if stream:
            return stream_response()

        resp = open_response()
        for _ in stream_response(resp):
            pass
        return chunks[-1] if chunks else {}
