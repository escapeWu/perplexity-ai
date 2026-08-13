from unittest.mock import MagicMock, patch

import pytest

from perplexity.server.app import run_query, run_query_stream


class RecordingStream:
    def __init__(self, chunks, error=None):
        self._chunks = iter(chunks)
        self._error = error
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self._chunks)
        except StopIteration:
            if self._error is not None:
                error, self._error = self._error, None
                raise error
            raise

    def close(self):
        self.closed = True


def make_client(*, response=None, stream=None):
    client = MagicMock()
    client.own = True
    client.subscription_tier = "pro"
    client.copilot = float("inf")
    client.file_upload = float("inf")
    if response is not None:
        client.search.return_value = response
    if stream is not None:
        client.search.return_value = stream
    return client


def make_pool(bound_client):
    pool = MagicMock()
    pool.clients = {"bound": object(), "other": object()}
    pool.get_client_by_id.return_value = ("bound", bound_client)
    pool.get_client_state.return_value = "normal"
    pool.get_client_weight.return_value = 100
    pool.is_incognito_enabled.return_value = False
    pool.get_search_timeout.return_value = 30
    pool.get_file_upload_timeout.return_value = 30
    return pool


def test_bound_non_stream_query_passes_cursor_and_returns_internal_metadata() -> None:
    follow_up = {"backend_uuid": "backend-0", "attachments": ["prior-file"]}
    client = make_client(
        response={
            "answer": "continued",
            "_follow_up": {"backend_uuid": "backend-1", "attachments": ["prior-file"]},
        }
    )
    pool = make_pool(client)

    with patch("perplexity.server.app.get_pool", return_value=pool):
        result = run_query(
            "next turn",
            mode="auto",
            bound_client_id="bound",
            follow_up=follow_up,
            include_internal_metadata=True,
        )

    assert result == {
        "status": "ok",
        "data": {
            "answer": "continued",
            "sources": [],
            "_follow_up": {"backend_uuid": "backend-1", "attachments": ["prior-file"]},
        },
    }
    pool.get_client_by_id.assert_called_once_with("bound", required_tier=None)
    pool.get_client.assert_not_called()
    assert client.search.call_args.kwargs["follow_up"] == follow_up
    pool.mark_client_success.assert_called_once_with("bound")


def test_bound_non_stream_query_never_fails_over() -> None:
    client = make_client()
    client.search.side_effect = RuntimeError("bound account failed")
    pool = make_pool(client)

    with patch("perplexity.server.app.get_pool", return_value=pool):
        result = run_query("question", mode="auto", bound_client_id="bound")

    assert result["status"] == "error"
    assert result["message"] == "bound account failed"
    assert client.search.call_count == 1
    pool.get_client.assert_not_called()
    pool.mark_client_failure.assert_called_once_with("bound")


def test_bound_non_stream_query_reports_unavailable_account() -> None:
    pool = make_pool(None)
    pool.get_client_by_id.return_value = ("bound", None)

    with patch("perplexity.server.app.get_pool", return_value=pool):
        result = run_query("question", mode="auto", bound_client_id="bound")

    assert result["status"] == "error"
    assert "Bound account 'bound' is unavailable" in result["message"]
    pool.get_client.assert_not_called()


def test_bound_stream_query_passes_cursor_and_never_uses_rotation() -> None:
    upstream = RecordingStream(
        [
            {
                "answer": "continued",
                "_follow_up": {"backend_uuid": "backend-1", "attachments": []},
            }
        ]
    )
    client = make_client(stream=upstream)
    pool = make_pool(client)
    follow_up = {"backend_uuid": "backend-0", "attachments": []}

    with patch("perplexity.server.app.get_pool", return_value=pool):
        chunks = list(
            run_query_stream(
                "next turn",
                mode="auto",
                bound_client_id="bound",
                follow_up=follow_up,
            )
        )

    assert chunks[0]["_follow_up"]["backend_uuid"] == "backend-1"
    assert upstream.closed is True
    assert client.search.call_args.kwargs["follow_up"] == follow_up
    pool.get_client.assert_not_called()
    pool.mark_client_success.assert_called_once_with("bound")


def test_bound_stream_query_does_not_switch_after_pre_event_failure() -> None:
    client = make_client(stream=RecordingStream([], RuntimeError("failed before event")))
    pool = make_pool(client)

    with patch("perplexity.server.app.get_pool", return_value=pool):
        with pytest.raises(RuntimeError, match="failed before event"):
            list(run_query_stream("question", mode="auto", bound_client_id="bound"))

    assert client.search.call_count == 1
    pool.get_client.assert_not_called()
    pool.mark_client_failure.assert_called_once_with("bound")
