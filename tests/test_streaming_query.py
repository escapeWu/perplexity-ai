"""Unit tests for the pool-aware upstream streaming query path."""

from unittest.mock import MagicMock, patch

import pytest

from perplexity.server.app import run_query_stream


class RecordingStream:
    def __init__(self, items, error=None):
        self._items = iter(items)
        self._error = error
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self._items)
        except StopIteration:
            if self._error is not None:
                error, self._error = self._error, None
                raise error
            raise

    def close(self):
        self.closed = True


def make_client(stream):
    client = MagicMock()
    client.own = True
    client.copilot = float("inf")
    client.file_upload = float("inf")
    client.search.return_value = stream
    return client


def make_pool(clients):
    pool = MagicMock()
    pool.clients = {client_id: object() for client_id, _ in clients}
    pool.get_client.side_effect = clients
    pool.get_client_state.return_value = "normal"
    pool.get_client_weight.return_value = 100
    pool.is_fallback_to_auto_enabled.return_value = False
    pool.is_incognito_enabled.return_value = False
    pool.get_search_timeout.return_value = 30
    pool.get_file_upload_timeout.return_value = 30
    return pool


def test_stream_query_marks_success_only_after_upstream_completion():
    stream = RecordingStream([{"answer": "one"}, {"answer": "one two"}])
    client = make_client(stream)
    pool = make_pool([("account", client)])

    with patch("perplexity.server.app.get_pool", return_value=pool):
        chunks = list(run_query_stream("test", mode="auto"))

    assert chunks == [{"answer": "one"}, {"answer": "one two"}]
    assert stream.closed is True
    pool.mark_client_success.assert_called_once_with("account")
    pool.mark_client_failure.assert_not_called()
    assert client.search.call_args.kwargs["stream"] is True


def test_stream_query_fails_over_before_first_upstream_event():
    failed_stream = RecordingStream([], RuntimeError("connection failed"))
    successful_stream = RecordingStream([{"answer": "ok"}])
    failed_client = make_client(failed_stream)
    successful_client = make_client(successful_stream)
    pool = make_pool([("failed", failed_client), ("successful", successful_client)])

    with patch("perplexity.server.app.get_pool", return_value=pool):
        chunks = list(run_query_stream("test", mode="auto"))

    assert chunks == [{"answer": "ok"}]
    pool.mark_client_failure.assert_called_once_with("failed")
    pool.mark_client_success.assert_called_once_with("successful")
    assert pool.get_client.call_args_list[1].kwargs["exclude_ids"] == {"failed"}


def test_stream_query_does_not_fail_over_after_an_event_was_yielded():
    failed_stream = RecordingStream([{"answer": "partial"}], RuntimeError("stream interrupted"))
    first_client = make_client(failed_stream)
    second_client = make_client(RecordingStream([{"answer": "replacement"}]))
    pool = make_pool([("first", first_client), ("second", second_client)])

    with patch("perplexity.server.app.get_pool", return_value=pool):
        stream = run_query_stream("test", mode="auto")
        assert next(stream) == {"answer": "partial"}
        with pytest.raises(RuntimeError, match="stream interrupted"):
            next(stream)

    pool.mark_client_failure.assert_called_once_with("first")
    second_client.search.assert_not_called()


def test_closing_stream_closes_upstream_without_marking_success():
    upstream = RecordingStream([{"answer": "partial"}, {"answer": "unused"}])
    client = make_client(upstream)
    pool = make_pool([("account", client)])

    with patch("perplexity.server.app.get_pool", return_value=pool):
        stream = run_query_stream("test", mode="auto")
        assert next(stream) == {"answer": "partial"}
        stream.close()

    assert upstream.closed is True
    pool.mark_client_success.assert_not_called()
    pool.mark_client_failure.assert_not_called()
