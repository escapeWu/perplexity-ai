
import json
import pytest
from unittest.mock import MagicMock, patch
from perplexity.server.app import run_query, get_pool, ClientPool, ValidationError

# --- Mock Data ---

VALID_TOKEN_CONFIG = {
  "heart_beat": {
    "enable": True,
    "question": "现在是农历几月几号？",
    "interval": 48,
    "tg_bot_token": "mock_token",
    "tg_chat_id": "mock_chat_id"
  },
  "tokens": [
    {
      "id": "valid_user@example.com",
      "csrf_token": "valid_csrf",
      "session_token": "valid_session"
    }
  ]
}

INVALID_TOKEN_CONFIG = {
  "tokens": [
    {
      "id": "invalid_user@example.com",
      "csrf_token": "invalid_csrf",
      "session_token": "invalid_session"
    }
  ]
}

MULTI_ACCOUNT_CONFIG = {
  "tokens": [
    {
      "id": "fail_user@example.com",
      "csrf_token": "fail_csrf",
      "session_token": "fail_session"
    },
    {
      "id": "valid_user@example.com",
      "csrf_token": "valid_csrf",
      "session_token": "valid_session"
    }
  ]
}


@pytest.fixture
def mock_pool(tmp_path, monkeypatch):
    """Use only synthetic credentials in an isolated config file."""
    config_file = tmp_path / "pool.json"
    config_file.write_text(json.dumps(INVALID_TOKEN_CONFIG))
    pool = ClientPool(str(config_file))
    pool.close()
    pool.clients = {}
    pool._rotation_order = []
    monkeypatch.setattr("perplexity.server.app.get_pool", lambda: pool)
    monkeypatch.setattr("time.sleep", lambda _: None)
    return pool

def test_single_account_retry_failure(mock_pool, tmp_path):
    """
    Scenario 1: Single account, always fails.
    Verify: Executes once on the failing account, then returns an error.
    """
    # Setup config file
    config_file = tmp_path / "token_pool_config.json"
    with open(config_file, "w") as f:
        json.dump(INVALID_TOKEN_CONFIG, f)

    mock_pool._load_from_config(str(config_file))

    # Mock client.search to always raise exception
    mock_client_instance = MagicMock(cookies={})
    mock_client_instance.search.side_effect = Exception("Network Error")
    mock_client_instance.own = True
    mock_client_instance.copilot = 0
    mock_client_instance.file_upload = 0

    # Replace the real client in the pool with our mock
    wrapper = mock_pool.clients["invalid_user@example.com"]
    wrapper.client = mock_client_instance

    # Run query
    result = run_query("test query", mode="auto")

    # Assertions
    assert result["status"] == "error"
    assert "Network Error" in result["message"]

    # Unknown network outcomes must not blindly replay the same query.
    assert mock_client_instance.search.call_count == 1

    # Verify client marked as failed
    assert wrapper.fail_count > 0


def test_failover_to_valid_account(mock_pool, tmp_path):
    """
    Scenario 2: Multi-account (Fail -> Valid).
    Verify: Tries failed account, fails, switches to valid account, succeeds.
    """
    # Setup config file
    config_file = tmp_path / "token_pool_config.json"
    with open(config_file, "w") as f:
        json.dump(MULTI_ACCOUNT_CONFIG, f)

    mock_pool._load_from_config(str(config_file))

    # Ensure specific order: fail_user first, valid_user second
    mock_pool._rotation_order = ["fail_user@example.com", "valid_user@example.com"]
    mock_pool._index = 0

    # Mock Fail Client
    fail_client = MagicMock(cookies={})
    fail_client.search.side_effect = Exception("Connection Refused")
    fail_client.own = True
    fail_client.copilot = 0
    fail_client.file_upload = 0
    mock_pool.clients["fail_user@example.com"].client = fail_client

    # Mock Valid Client
    valid_client = MagicMock(cookies={})
    valid_client.search.return_value = {
        "answer": "Success Answer",
        "text": [{"step_type": "SEARCH_RESULTS", "content": {"web_results": [{"url": "http://example.com"}]}}]
    }
    valid_client.own = True
    valid_client.copilot = 0
    valid_client.file_upload = 0
    mock_pool.clients["valid_user@example.com"].client = valid_client

    # Run query
    result = run_query("test query", mode="auto")

    # Assertions
    assert result["status"] == "ok"
    assert result["data"]["answer"] == "Success Answer"

    # The compatibility helper makes one attempt per selected account.
    assert fail_client.search.call_count == 1

    # Verify Valid Client was called once
    assert valid_client.search.call_count == 1

    # Verify Fail Client marked as failed
    assert mock_pool.clients["fail_user@example.com"].fail_count > 0

    # Verify Valid Client marked as success
    assert mock_pool.clients["valid_user@example.com"].fail_count == 0

def test_pro_quota_failover(mock_pool, tmp_path):
    """
    Scenario 3: Pro Mode Quota Exhaustion.
    Verify: Fails immediately on quota error (no retry), switches to next client.
    """
    # Setup config file
    config_file = tmp_path / "token_pool_config.json"
    with open(config_file, "w") as f:
        json.dump(MULTI_ACCOUNT_CONFIG, f)

    mock_pool._load_from_config(str(config_file))
    mock_pool._rotation_order = ["fail_user@example.com", "valid_user@example.com"]
    mock_pool._index = 0

    # Mock Quota Fail Client
    fail_client = MagicMock(cookies={})
    fail_client.search.side_effect = Exception("Your Pro search quota has run out")
    fail_client.own = True
    fail_client.copilot = float("inf")
    fail_client.file_upload = 0
    mock_pool.clients["fail_user@example.com"].client = fail_client

    # Mock Valid Client
    valid_client = MagicMock(cookies={})
    valid_client.search.return_value = {"answer": "Pro Answer"}
    valid_client.own = True
    valid_client.copilot = float("inf")
    valid_client.file_upload = 0
    mock_pool.clients["valid_user@example.com"].client = valid_client

    # Run query in PRO mode
    result = run_query("test query", mode="pro")

    # Assertions
    assert result["status"] == "ok"
    assert result["data"]["answer"] == "Pro Answer"

    # Verify Quota Fail Client was called ONCE (no retries for quota errors)
    assert fail_client.search.call_count == 1

    # Verify Valid Client was called
    assert valid_client.search.call_count == 1

    # Verify Pro Failure marked
    assert mock_pool.clients["fail_user@example.com"].pro_fail_count > 0
