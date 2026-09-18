"""Real local sockets exercise curl cancellation, framing and validation (no upstream account)."""
import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from perplexity import upstream_async
from perplexity.upstream_protocol import UpstreamError


class Client:
    def prepare_search(self, *args):
        return {"params": {"attachments": [], "model_preference": "test"}}, {}

    def cookie_snapshot(self):
        return 0, {}

    def merge_cookies(self, *args):
        pass


def event(data):
    return b"event: message\r\ndata: " + json.dumps(data).encode() + b"\r\n\r\n"


@asynccontextmanager
async def endpoint(monkeypatch, handler):
    tasks = set()
    async def serve(reader, writer):
        tasks.add(asyncio.current_task())
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            for line in headers.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    await reader.readexactly(int(line.split(b":")[1]))
            await handler(reader, writer)
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(asyncio.current_task())
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    monkeypatch.setattr(upstream_async, "ENDPOINT_SSE_ASK", f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/ask")
    monkeypatch.setattr(upstream_async, "SOCKS_PROXY", None)
    try:
        yield
    finally:
        server.close()
        await server.wait_closed()
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*list(tasks), return_exceptions=True)


async def collect():
    return [chunk async for chunk in upstream_async.search_stream(Client(), query="test", mode="auto")]


@pytest.mark.asyncio
async def test_terminal_metadata_preserves_answer(monkeypatch):
    async def handler(reader, writer):
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n")
        writer.write(event({"answer": "complete answer", "backend_uuid": "a", "status": "PENDING"}))
        writer.write(event({"status": "COMPLETED", "final_sse_message": True, "text_completed": True}))
        writer.write(b"event: end_of_stream\r\ndata: {}\r\n\r\n")
        await writer.drain()
    async with endpoint(monkeypatch, handler):
        chunks = await collect()
    assert chunks[-1]["answer"] == "complete answer"
    assert chunks[-1]["_follow_up"]["backend_uuid"] == "a"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,code", [
    (429, b'{}', "upstream_rate_limited"),
    (200, event({"status": "COMPLETED", "backend_uuid": "a"}) + b"event: end_of_stream\n\n", "empty_answer"),
    (200, event({"answer": "partial", "status": "PENDING"}), "upstream_incomplete"),
])
async def test_rejects_false_success(monkeypatch, status, body, code):
    async def handler(reader, writer):
        writer.write(f"HTTP/1.1 {status} OK\r\nContent-Type: text/event-stream\r\nRetry-After: 1\r\nConnection: close\r\n\r\n".encode() + body)
        await writer.drain()
    async with endpoint(monkeypatch, handler):
        with pytest.raises(UpstreamError) as failure:
            await collect()
    assert failure.value.code == code


@pytest.mark.asyncio
async def test_cancel_closes_idle_socket_without_affecting_other_job(monkeypatch):
    accepted, closed = [], asyncio.Event()
    async def handler(reader, writer):
        accepted.append(writer)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n")
        writer.write(event({"status": "PENDING", "backend_uuid": str(len(accepted))}))
        await writer.drain()
        await reader.read()
        closed.set()
    async with endpoint(monkeypatch, handler):
        a, b = asyncio.create_task(collect()), asyncio.create_task(collect())
        try:
            async def both():
                while len(accepted) < 2:
                    await asyncio.sleep(0.005)
            await asyncio.wait_for(both(), 2)
            a.cancel()
            with pytest.raises(asyncio.CancelledError):
                await a
            await asyncio.wait_for(closed.wait(), 1)
            assert not b.done()
        finally:
            b.cancel()
            await asyncio.gather(a, b, return_exceptions=True)


@pytest.mark.asyncio
async def test_input_budget_aborts_transfer(monkeypatch):
    monkeypatch.setattr(upstream_async, "MAX_RESPONSE_BYTES", 1024)
    async def handler(reader, writer):
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n" + b"x" * 32768)
        await writer.drain()
    async with endpoint(monkeypatch, handler):
        with pytest.raises(UpstreamError) as failure:
            await collect()
    assert failure.value.code == "buffer_limit"
