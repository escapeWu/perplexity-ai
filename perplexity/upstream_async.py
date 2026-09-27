"""Task-owned async curl transport with bounded input and deterministic cancellation."""
from __future__ import annotations

import asyncio
import mimetypes
from contextlib import suppress
from typing import AsyncIterator

from curl_cffi import CurlMime, CurlOpt
from curl_cffi.requests import AsyncSession

from .client import Client, annotate_model_downgrade, uploaded_file_url, scoped_cookies
from .config import DEFAULT_HEADERS, ENDPOINT_AUTH_SESSION, ENDPOINT_SSE_ASK, ENDPOINT_UPLOAD_URL, SOCKS_PROXY
from .upstream_protocol import MAX_RESPONSE_BYTES, ResponseState, SSEDecoder, UpstreamError, check_response, check_http_status


async def refresh_account(client: Client):
    generation, cookies = client.cookie_snapshot()
    async with AsyncSession(headers=DEFAULT_HEADERS.copy(), cookies=scoped_cookies(cookies), impersonate="chrome",
                            proxy=SOCKS_PROXY.split("#")[0] if SOCKS_PROXY else None) as session:
        # Account-scoped session requires x-pplx-account; recover the id from cookies.
        hint = client.account_hint()
        req_headers = {"x-pplx-account": hint} if hint else None
        response = await session.get(ENDPOINT_AUTH_SESSION, headers=req_headers, timeout=20)
        if response.status_code in (401, 403):
            raise UpstreamError("Account authentication failed", "account_unavailable")
        if response.status_code == 429:
            raise UpstreamError("Account lookup was rate limited", "upstream_rate_limited", retry_after=1)
        if response.status_code != 200:
            raise UpstreamError("Account lookup failed", "upstream_http_error")
        data = response.json()
        client._update_user_info(data)
        client.merge_cookies(generation, cookies, session.cookies.get_dict())
        return data


async def search_stream(client: Client, *, query: str, mode: str, model=None,
                        sources=None, language="en-US", follow_up=None, incognito=False,
                        files=None, timeout=300, file_upload_timeout=180) -> AsyncIterator[dict]:
    """One connection owner per task. Cancelling this generator closes only its I/O."""
    files = files or {}
    client.prepare_search(query, mode, model, sources, language, follow_up, incognito)
    generation, original_cookies = client.cookie_snapshot()
    async with AsyncSession(headers=DEFAULT_HEADERS.copy(), cookies=scoped_cookies(original_cookies),
                            impersonate="chrome", max_clients=1,
                            proxy=SOCKS_PROXY.split("#")[0] if SOCKS_PROXY else None) as session:
        uploaded = []
        for filename, content in files.items():
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            sign = await session.post(ENDPOINT_UPLOAD_URL,
                params={"version": "2.18", "source": "default"},
                json={"content_type": content_type, "file_size": len(content),
                      "filename": filename, "force_image": False, "source": "default"},
                timeout=20)
            check_http_status(sign.status_code, sign.headers)
            info = sign.json()
            multipart = CurlMime()
            try:
                for key, value in info["fields"].items():
                    multipart.addpart(name=key, data=value)
                multipart.addpart(name="file", filename=filename, content_type=content_type, data=content)
                response = await session.post(info["s3_bucket_url"], multipart=multipart,
                                              timeout=file_upload_timeout)
                check_http_status(response.status_code, response.headers)
                uploaded.append(uploaded_file_url(info, response))
            finally:
                multipart.close()
        payload, headers = client.prepare_search(query, mode, model, sources, language,
                                                 follow_up, incognito, uploaded)
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=128)
        buffered = 0
        header_bytes = 0
        status = 0
        response_headers = {}
        callback_error = None

        def receive_header(line):
            nonlocal status, header_bytes, callback_error
            header_bytes += len(line)
            if header_bytes > 65536:
                callback_error = UpstreamError("Response headers exceed budget", "buffer_limit")
                return 0
            if line.startswith(b"HTTP/"):
                response_headers.clear()
                try:
                    status = int(line.split()[1])
                except (ValueError, IndexError):
                    status = 0
            elif b":" in line:
                name, value = line.split(b":", 1)
                # Capture only fields needed for protocol checks, never cookie headers.
                key = name.decode("ascii", errors="ignore").lower()
                if key in ("content-type", "retry-after"):
                    response_headers[key] = value.decode("latin1").strip()
            return len(line)

        def receive_body(chunk):
            nonlocal buffered, callback_error
            if callback_error:
                return 0
            try:
                check_response(status, response_headers)
                if buffered + len(chunk) > MAX_RESPONSE_BYTES or queue.full():
                    raise UpstreamError("Upstream input buffer exceeded budget", "buffer_limit")
                queue.put_nowait(bytes(chunk))
                buffered += len(chunk)
                return len(chunk)
            except UpstreamError as exc:
                callback_error = exc
                return 0  # curl aborts the transfer instead of allocating an unbounded queue.

        session.curl_options[CurlOpt.HEADERFUNCTION] = receive_header
        session.curl_options[CurlOpt.CONNECTTIMEOUT_MS] = 20000
        decoder = SSEDecoder()
        state = ResponseState(payload["params"]["attachments"])
        transfer = asyncio.create_task(session.post(
            ENDPOINT_SSE_ASK, json=payload, headers=headers, stream=False,
            content_callback=receive_body, timeout=timeout, allow_redirects=False,
        ))
        reader = None
        try:
            while not transfer.done() or not queue.empty():
                if queue.empty():
                    reader = asyncio.create_task(queue.get())
                    done, _ = await asyncio.wait({reader, transfer}, return_when=asyncio.FIRST_COMPLETED)
                    if reader not in done:
                        reader.cancel()
                        await asyncio.gather(reader, return_exceptions=True)
                        reader = None
                        break
                    chunk = reader.result()
                    reader = None
                else:
                    chunk = queue.get_nowait()
                buffered -= len(chunk)
                for event, text in decoder.feed(chunk):
                    normalized = state.feed(event, text)
                    if normalized is not None:
                        annotate_model_downgrade(normalized, payload["params"]["model_preference"] if model else None)
                        yield normalized
            if callback_error:
                raise callback_error
            response = await transfer
            check_response(response.status_code, response_headers)
            state.finish()
            client.merge_cookies(generation, original_cookies, session.cookies.get_dict())
        except asyncio.CancelledError:
            raise
        except UpstreamError:
            raise
        except Exception as exc:
            if callback_error:
                raise callback_error from None
            raise UpstreamError("Upstream transport failed", "upstream_transport_error") from exc
        finally:
            if reader is not None:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
            if not transfer.done():
                transfer.cancel()
            # AsyncSession.request releases/removes its curl handle in finally on cancellation.
            # Waiting for that unwind before closing the session avoids orphan transfers.
            await asyncio.gather(transfer, return_exceptions=True)
