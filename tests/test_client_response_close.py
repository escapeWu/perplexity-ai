"""Regression tests for closing synchronous streaming responses."""

import json
from typing import Iterable

import pytest

from perplexity.client import Client


MESSAGE = b'event: message\r\ndata: {"answer": "ok"}'
END = b"event: end_of_stream\r\n"


def message(payload) -> bytes:
    return b"event: message\r\ndata: " + json.dumps(payload).encode()


class FakeResponse:
    def __init__(self, chunks: Iterable[bytes]):
        self.chunks = chunks
        self.close_count = 0

    def iter_lines(self, delimiter: bytes):
        assert delimiter == b"\r\n\r\n"
        return iter(self.chunks)

    def close(self) -> None:
        self.close_count += 1


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.post_count = 0

    def post(self, *args, **kwargs) -> FakeResponse:
        self.post_count += 1
        return self.response


def make_client(response: FakeResponse) -> Client:
    client = Client.__new__(Client)
    client.session = FakeSession(response)
    client.own = True
    client.copilot = float("inf")
    client.file_upload = float("inf")
    return client


def test_stream_response_closes_after_natural_completion() -> None:
    response = FakeResponse([MESSAGE, END])

    chunks = list(make_client(response).search("test", stream=True))

    assert chunks == [{"answer": "ok"}]
    assert response.close_count == 1


def test_unused_stream_does_not_open_a_response() -> None:
    response = FakeResponse([MESSAGE, END])
    client = make_client(response)

    stream = client.search("test", stream=True)
    stream.close()

    assert client.session.post_count == 0
    assert response.close_count == 0


def test_stream_response_closes_when_consumer_stops_early() -> None:
    response = FakeResponse([MESSAGE, MESSAGE, END])
    stream = make_client(response).search("test", stream=True)

    assert next(stream) == {"answer": "ok"}
    stream.close()

    assert response.close_count == 1


def test_stream_response_closes_after_iterator_error() -> None:
    def failing_chunks():
        yield MESSAGE
        raise RuntimeError("connection failed")

    response = FakeResponse(failing_chunks())
    stream = make_client(response).search("test", stream=True)

    assert next(stream) == {"answer": "ok"}
    with pytest.raises(RuntimeError, match="connection failed"):
        next(stream)

    assert response.close_count == 1


def test_non_stream_response_closes_after_completion() -> None:
    response = FakeResponse([MESSAGE, END])

    result = make_client(response).search("test")

    assert result == {"answer": "ok"}
    assert response.close_count == 1


def test_non_stream_response_closes_after_decode_error() -> None:
    response = FakeResponse([b"\xff"])

    with pytest.raises(UnicodeDecodeError):
        make_client(response).search("test")

    assert response.close_count == 1


def test_stream_normalizes_incremental_block_payloads() -> None:
    response = FakeResponse(
        [
            message({"blocks": []}),
            message(
                {
                    "blocks": [
                        {
                            "web_result_block": {
                                "progress": "IN_PROGRESS",
                                "web_results": [{"url": "https://example.com", "name": "Example"}],
                            }
                        }
                    ]
                }
            ),
            message(
                {
                    "blocks": [
                        {
                            "markdown_block": {
                                "progress": "IN_PROGRESS",
                                "chunks": ["Hel", "l"],
                                "chunk_starting_offset": 0,
                            }
                        }
                    ]
                }
            ),
            message(
                {
                    "blocks": [
                        {
                            "markdown_block": {
                                "progress": "IN_PROGRESS",
                                "chunks": ["o"],
                                "chunk_starting_offset": 2,
                            }
                        }
                    ]
                }
            ),
            END,
        ]
    )

    chunks = list(make_client(response).search("test", stream=True))

    assert [step["step_type"] for step in chunks[0]["text"]] == ["INITIAL_QUERY"]
    assert chunks[1]["chunks"] == [{"url": "https://example.com", "name": "Example"}]
    assert chunks[2]["answer"] == "Hell"
    assert chunks[3]["answer"] == "Hello"
