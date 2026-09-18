import json
import pytest
from unittest.mock import MagicMock, patch
from perplexity.server.app import run_query, get_pool
from perplexity.server.client_pool import ClientPool

# Synthetic credentials only; never copy a developer's local token fixture.
TEST_CONFIG = {"tokens": [
    {"id": name, "csrf_token": "fixture-csrf", "session_token": "fixture-session"}
    for name in ("account-a", "account-b")
]}

@pytest.fixture
def mock_pool(tmp_path, monkeypatch):
    """Tests must not write the shared test fixture or bootstrap a real account pool."""
    path = tmp_path / "pool.json"
    path.write_text(json.dumps(TEST_CONFIG))
    pool = ClientPool(str(path))
    monkeypatch.setattr("perplexity.server.app.get_pool", lambda: pool)
    yield pool
    pool.close()

def test_single_account_all_retries_fail(mock_pool):
    """
    Scenario 1: Single faulty account.
    Expectation: One attempt, without blindly replaying an ambiguous network failure.
    """
    # Setup: Only keep one client in the pool
    mock_pool.clients = {k: v for k, v in list(mock_pool.clients.items())[:1]}
    mock_pool._rotation_order = list(mock_pool.clients.keys())

    single_client_id = mock_pool._rotation_order[0]
    wrapper = mock_pool.clients[single_client_id]

    # Mock search on the actual client instance
    mock_search = MagicMock(side_effect=Exception("Network Error"))
    wrapper.client.search = mock_search

    # Execute
    with patch("time.sleep"):
        result = run_query("test query", mode="auto")

    # Verification
    assert result["status"] == "error"
    assert result["message"] == "Network Error"

    # One attempt on this account; an unknown upstream outcome is not retried.
    assert mock_search.call_count == 1

    # Verify the client was marked as failed (backoff applied)
    assert wrapper.fail_count > 0
    assert not wrapper.is_available()

def test_failover_to_next_account(mock_pool):
    """
    Scenario 2: Multi-account failover.
    Expectation: A failed account is tried once, then the legacy helper selects the next account.
    """
    # Ensure we have at least 2 clients
    assert len(mock_pool.clients) >= 2
    client_ids = mock_pool._rotation_order
    first_client_id = client_ids[0]
    second_client_id = client_ids[1]

    first_wrapper = mock_pool.clients[first_client_id]
    second_wrapper = mock_pool.clients[second_client_id]

    # Track call counts per client
    call_tracker = {"first": 0, "second": 0}

    def first_client_side_effect(*args, **kwargs):
        call_tracker["first"] += 1
        raise Exception(f"Fail {call_tracker['first']}")

    def second_client_side_effect(*args, **kwargs):
        call_tracker["second"] += 1
        return {"answer": "Success", "text": []}

    # Mock search on actual client instances
    first_wrapper.client.search = MagicMock(side_effect=first_client_side_effect)
    second_wrapper.client.search = MagicMock(side_effect=second_client_side_effect)

    # Execute
    with patch("time.sleep"):
        result = run_query("test query", mode="auto")

    # Verification
    assert result["status"] == "ok"
    assert result["data"]["answer"] == "Success"

    # The first account was attempted once.
    assert call_tracker["first"] == 1

    # Second client should have been called once (success)
    assert call_tracker["second"] == 1

    # First client should be marked failed
    assert first_wrapper.fail_count > 0

    # Second client should be successful (fail_count reset/0)
    assert second_wrapper.fail_count == 0

def test_pro_limit_immediate_failover(mock_pool):
    """
    Scenario 3: Pro limit error should trigger immediate failover (no retries on same client).
    """
    # Ensure we have at least 2 clients
    assert len(mock_pool.clients) >= 2
    client_ids = mock_pool._rotation_order
    first_client_id = client_ids[0]
    second_client_id = client_ids[1]

    first_wrapper = mock_pool.clients[first_client_id]
    second_wrapper = mock_pool.clients[second_client_id]

    # Track call counts per client
    call_tracker = {"first": 0, "second": 0}

    def first_client_side_effect(*args, **kwargs):
        call_tracker["first"] += 1
        raise Exception("You have reached your pro limit")

    def second_client_side_effect(*args, **kwargs):
        call_tracker["second"] += 1
        return {"answer": "Success", "text": []}

    # Mock search on actual client instances
    first_wrapper.client.search = MagicMock(side_effect=first_client_side_effect)
    second_wrapper.client.search = MagicMock(side_effect=second_client_side_effect)

    with patch("time.sleep"):
        result = run_query("test query", mode="pro")

    assert result["status"] == "ok"
    # Should only call once per client - pro limit triggers immediate failover (no retries)
    assert call_tracker["first"] == 1
    assert call_tracker["second"] == 1
