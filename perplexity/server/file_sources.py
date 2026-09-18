"""Bounded attachment resolution with pinned public destinations for remote URLs."""
from __future__ import annotations

import base64
import ipaddress
import os
import socket
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from curl_cffi import CurlOpt, requests

from ..config import ALLOWED_FILE_EXTENSIONS
from .files_store import MAX_FILE_BYTES, MAX_REQUEST_FILE_BYTES, get_files_store


def validate_extension(filename):
    if not isinstance(filename, str) or not filename.strip() or len(filename.encode()) > 1024:
        raise ValueError("Invalid attachment filename")
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_FILE_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {extension}")


def resolve_file_data(part):
    filename = part.get("filename", "")
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("input_file with file_data requires a filename")
    validate_extension(filename)
    raw = part.get("file_data", "")
    if not isinstance(raw, str):
        raise ValueError("file_data must be base64 text")
    if raw.startswith("data:"):
        if ";base64," not in raw:
            raise ValueError("file_data data URL must use base64 encoding")
        raw = raw.split(";base64,", 1)[1]
    if len(raw) > ((MAX_FILE_BYTES + 2) // 3) * 4:
        raise ValueError("File exceeds 20 MiB limit")
    try:
        data = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid base64 file_data") from exc
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File exceeds 20 MiB limit")
    return Path(filename).name, data


def public_destination(url):
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
        raise ValueError("file_url requires an HTTP(S) URL without credentials")
    host = parts.hostname.encode("idna").decode("ascii")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        addresses = {row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError("Unable to resolve file_url host") from exc
    if not addresses:
        raise ValueError("file_url host has no addresses")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        mapped = getattr(ip, "ipv4_mapped", None)
        if not ip.is_global or ip.is_multicast or (mapped and not mapped.is_global):
            raise ValueError("file_url must resolve only to public addresses")
    address = sorted(addresses)[0]
    pinned = f"[{address}]" if ":" in address else address
    return f"{host}:{port}:{pinned}"


def resolve_file_url(part, *, deadline=None):
    deadline = time.monotonic() + 30 if deadline is None else deadline
    url = part.get("file_url", "")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("file_url must be a non-empty string")
    filename = part.get("filename") or Path(unquote(urlsplit(url).path)).name or "file"
    validate_extension(filename)
    for _ in range(4):
        destination = public_destination(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Attachment download deadline exceeded")
        body = bytearray()
        overflow = False
        def receive(chunk):
            nonlocal overflow
            if len(body) + len(chunk) > MAX_FILE_BYTES:
                overflow = True
                return 0
            body.extend(chunk)
            return len(chunk)
        try:
            # Pin the validated address and disable proxy/env DNS paths to prevent rebinding.
            with requests.Session(trust_env=False, curl_options={
                CurlOpt.RESOLVE: [destination], CurlOpt.PROXY: "",
            }) as session:
                response = session.get(url, allow_redirects=False, timeout=min(30, remaining), content_callback=receive)
        except Exception as exc:
            raise ValueError("File exceeds size limit" if overflow else "Unable to download file_url") from exc
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location")
            if not location:
                raise ValueError("File redirect has no location")
            url = urljoin(url, location)
            continue
        if response.status_code != 200:
            raise ValueError(f"File download returned HTTP {response.status_code}")
        return filename, bytes(body)
    raise ValueError("Too many file_url redirects")


def resolve_file_id(part):
    file_id = part.get("file_id", "")
    if not isinstance(file_id, str) or not file_id.strip():
        raise ValueError("file_id must be a non-empty string")
    entry = get_files_store().get(file_id)
    if entry is None:
        raise LookupError("Requested file is missing or expired")
    return entry.filename, entry.data


def resolve_input_file(part, *, deadline=None):
    keys = [key for key in ("file_data", "file_url", "file_id") if key in part]
    if len(keys) != 1:
        raise ValueError("input_file requires exactly one of file_data, file_url or file_id")
    if keys[0] == "file_url":
        return resolve_file_url(part, deadline=deadline)
    return {"file_data": resolve_file_data, "file_id": resolve_file_id}[keys[0]](part)


def extract_files(messages):
    files, total, count = {}, 0, 0
    deadline = time.monotonic() + 30
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("Each messages entry must be an object")
        content = message.get("content", "")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "input_file":
                continue
            count += 1
            if count > 10:
                raise ValueError("A request may contain at most 10 files")
            if time.monotonic() >= deadline:
                raise ValueError("Attachment resolution deadline exceeded")
            filename, data = resolve_input_file(part, deadline=deadline)
            total += len(data)
            if total > MAX_REQUEST_FILE_BYTES:
                raise ValueError("Attachments exceed request size limit")
            if filename in files:
                raise ValueError("Attachment filenames must be unique")
            files[filename] = data
    return files


def normalize_mcp_files(files):
    if not files:
        return {}
    if isinstance(files, dict):
        if len(files) > 10:
            raise ValueError("A request may contain at most 10 files")
        result = {name: value.encode() if isinstance(value, str) else value for name, value in files.items()}
    else:
        if isinstance(files, (str, bytes)):
            raise ValueError("files must be an object or a list of paths")
        roots = [Path(value).expanduser().resolve() for value in os.getenv("PPLX_ALLOWED_FILE_ROOTS", "").split(os.pathsep) if value]
        if not roots:
            raise ValueError("Server file paths are disabled; upload files or configure PPLX_ALLOWED_FILE_ROOTS")
        result = {}
        total = 0
        for index, name in enumerate(files):
            if index >= 10:
                raise ValueError("A request may contain at most 10 files")
            path = Path(name).expanduser().resolve()
            if not any(path.is_relative_to(root) for root in roots):
                raise ValueError("File path is outside allowed roots")
            if not path.is_file():
                raise ValueError("Only regular files may be attached")
            if path.name in result:
                raise ValueError("Attachment filenames must be unique")
            validate_extension(path.name)
            with path.open("rb") as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
            total += len(data)
            if len(data) > MAX_FILE_BYTES or total > MAX_REQUEST_FILE_BYTES:
                raise ValueError("Attachments exceed size limit")
            result[path.name] = data
    if len(result) > 10 or any(not isinstance(data, bytes) or len(data) > MAX_FILE_BYTES for data in result.values()):
        raise ValueError("Invalid attachment or file size limit exceeded")
    if sum(len(data) for data in result.values()) > MAX_REQUEST_FILE_BYTES:
        raise ValueError("Attachments exceed request size limit")
    for name in result:
        validate_extension(name)
    return result
