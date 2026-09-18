"""Offline protocol fixtures: actual runtime/storage with a controllable upstream boundary."""
import asyncio
import importlib
import ipaddress
import socket
from urllib.parse import urlsplit

import pytest
from curl_cffi.requests import Session, AsyncSession
from starlette.requests import Request


def pytest_collection_modifyitems(config, items):
    import os
    if os.getenv("PPLX_RUN_LIVE_TESTS") == "1":
        return
    for item in items:
        if item.path.name in {"test_oai.py", "test_mcp.py"}:
            item.add_marker(pytest.mark.skip(reason="Live server suite: explicitly set PPLX_RUN_LIVE_TESTS=1"))


@pytest.fixture(autouse=True)
def offline_boundary(monkeypatch, request, tmp_path):
    import os
    if os.getenv("PPLX_RUN_LIVE_TESTS") == "1" and request.path.name in {"test_oai.py", "test_mcp.py"}:
        return
    def local(host):
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return host == "localhost"
    original_connect = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and not local(address[0]):
            raise RuntimeError("External network is disabled in unit tests")
        return original_connect(sock, address)
    monkeypatch.setattr(socket.socket, "connect", connect)
    original_request = Session.request
    original_async = AsyncSession.request
    def sync_request(session, method, url, **kwargs):
        if not local(urlsplit(url).hostname or ""):
            raise RuntimeError("External network is disabled in unit tests")
        return original_request(session, method, url, **kwargs)
    async def async_request(session, method, url, **kwargs):
        if not local(urlsplit(url).hostname or ""):
            raise RuntimeError("External network is disabled in unit tests")
        return await original_async(session, method, url, **kwargs)
    monkeypatch.setattr(Session, "request", sync_request)
    monkeypatch.setattr(AsyncSession, "request", async_request)
    from perplexity.server import app
    from perplexity import model_registry
    monkeypatch.setattr(model_registry, "_registry", model_registry.ModelRegistry(cache_path=tmp_path / "unused-cache.json"))
    monkeypatch.setattr(app, "_pool", None)
    def unconfigured():
        raise AssertionError("This test must supply an isolated account pool/runtime")
    for name in ("app", "mcp", "oai", "webui", "admin"):
        monkeypatch.setattr(importlib.import_module("perplexity.server." + name), "get_pool", unconfigured)
    monkeypatch.setattr(app, "_job_runtime", None)
    monkeypatch.setattr(app, "_runtime_lock", None)


@pytest.fixture
async def api_runtime(tmp_path, monkeypatch):
    import json
    from tests.test_job_runtime import ControlledUpstream, FakeClient
    from perplexity.server import client_pool
    from perplexity.server.files_store import FilesStore
    from perplexity.server.job_runtime import JobRuntime
    from perplexity.server.webui_sessions import WebUISessionStore

    monkeypatch.setattr(client_pool, "Client", FakeClient)
    config = tmp_path / "pool.json"
    config.write_text(json.dumps({"tokens": [{"id": "one-account", "csrf_token": "fake", "session_token": "fake"}],
        "concurrency": {"max_concurrency": 8, "burst": 8, "start_rate": 100}}))
    pool = client_pool.ClientPool(str(config))
    source = ControlledUpstream()
    runtime = JobRuntime(WebUISessionStore(tmp_path / "sessions.db"), pool,
                         transport=source, files=FilesStore(tmp_path / "uploads"))
    runtime.test_upstream = source
    await runtime.start()
    async def get_runtime(*args):
        return runtime
    for name in ("oai", "webui", "jobs", "mcp", "app", "admin"):
        module = importlib.import_module("perplexity.server." + name)
        monkeypatch.setattr(module, "get_job_runtime", get_runtime, raising=False)
        monkeypatch.setattr(module, "get_pool", lambda: pool, raising=False)
    try:
        yield runtime
    finally:
        await runtime.close()


def request_for(path, body=None, *, method="POST", params=None, query="", token=True, disconnect=None, headers=None):
    import json
    from perplexity.server.oai import MCP_TOKEN
    delivered = False
    connected = disconnect or asyncio.Event()
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": json.dumps(body or {}).encode(), "more_body": False}
        await connected.wait()
        return {"type": "http.disconnect"}
    hdrs = [(b"authorization", f"Bearer {MCP_TOKEN}".encode())] if token else []
    hdrs.extend(headers or [])
    return Request({"type": "http", "method": method, "path": path, "headers": hdrs,
                    "query_string": query.encode(), "path_params": params or {}}, receive)
