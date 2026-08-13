"""
Tests for the ClientPool module.
"""

import json
import os
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest


class TestClientWrapper:
    """Tests for ClientWrapper class."""

    def test_initial_state(self):
        """Test that ClientWrapper initializes with correct default state."""
        from perplexity.server.client_pool import ClientWrapper

        mock_client = MagicMock()
        wrapper = ClientWrapper(mock_client, "test-id")

        assert wrapper.id == "test-id"
        assert wrapper.client == mock_client
        assert wrapper.fail_count == 0
        assert wrapper.available_after == 0
        assert wrapper.request_count == 0
        assert wrapper.is_available() is True

    def test_mark_success(self):
        """Test that mark_success increments request count and resets failure state."""
        from perplexity.server.client_pool import ClientWrapper

        mock_client = MagicMock()
        wrapper = ClientWrapper(mock_client, "test-id")

        # Simulate some failures first
        wrapper.fail_count = 3
        wrapper.available_after = time.time() + 100

        wrapper.mark_success()

        assert wrapper.fail_count == 0
        assert wrapper.available_after == 0
        assert wrapper.request_count == 1
        assert wrapper.is_available() is True

    def test_mark_failure_exponential_backoff(self):
        """Test that mark_failure applies exponential backoff."""
        from perplexity.server.client_pool import ClientWrapper

        mock_client = MagicMock()
        wrapper = ClientWrapper(mock_client, "test-id")

        # First failure: 60 seconds (INITIAL_BACKOFF)
        wrapper.mark_failure()
        assert wrapper.fail_count == 1
        assert wrapper.available_after > time.time()
        assert wrapper.available_after <= time.time() + ClientWrapper.INITIAL_BACKOFF + 1

        # Second failure: 120 seconds (60 * 2^1)
        wrapper.mark_failure()
        assert wrapper.fail_count == 2
        assert wrapper.available_after > time.time()
        assert wrapper.available_after <= time.time() + ClientWrapper.INITIAL_BACKOFF * 2 + 1

        # Third failure: 240 seconds (60 * 2^2)
        wrapper.mark_failure()
        assert wrapper.fail_count == 3
        assert wrapper.available_after > time.time()
        assert wrapper.available_after <= time.time() + ClientWrapper.INITIAL_BACKOFF * 4 + 1

    def test_mark_failure_max_backoff(self):
        """Test that backoff is capped at MAX_BACKOFF (3600 seconds)."""
        from perplexity.server.client_pool import ClientWrapper

        mock_client = MagicMock()
        wrapper = ClientWrapper(mock_client, "test-id")

        # Simulate many failures
        for _ in range(10):
            wrapper.mark_failure()

        assert wrapper.fail_count == 10
        # Backoff should be capped at MAX_BACKOFF (3600 seconds)
        assert wrapper.available_after <= time.time() + ClientWrapper.MAX_BACKOFF + 1

    def test_is_available_after_backoff(self):
        """Test that client becomes available after backoff period."""
        from perplexity.server.client_pool import ClientWrapper

        mock_client = MagicMock()
        wrapper = ClientWrapper(mock_client, "test-id")

        # Set available_after to past time
        wrapper.available_after = time.time() - 1

        assert wrapper.is_available() is True

    def test_is_not_available_during_backoff(self):
        """Test that client is not available during backoff period."""
        from perplexity.server.client_pool import ClientWrapper

        mock_client = MagicMock()
        wrapper = ClientWrapper(mock_client, "test-id")

        # Set available_after to future time
        wrapper.available_after = time.time() + 100

        assert wrapper.is_available() is False

    def test_get_status(self):
        """Test that get_status returns correct status dict."""
        from perplexity.server.client_pool import ClientWrapper

        mock_client = MagicMock()
        wrapper = ClientWrapper(mock_client, "test-id")
        wrapper.request_count = 5

        status = wrapper.get_status()

        assert status["id"] == "test-id"
        assert status["available"] is True
        assert status["fail_count"] == 0
        assert status["next_available_at"] is None
        assert status["request_count"] == 5

    def test_get_status_during_backoff(self):
        """Test that get_status returns next_available_at during backoff."""
        from perplexity.server.client_pool import ClientWrapper

        mock_client = MagicMock()
        wrapper = ClientWrapper(mock_client, "test-id")
        wrapper.mark_failure()

        status = wrapper.get_status()

        assert status["available"] is False
        assert status["next_available_at"] is not None
        assert "T" in status["next_available_at"]  # ISO8601 format


class TestClientPool:
    """Tests for ClientPool class."""

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_initialize_anonymous_mode(self, mock_client_class, mock_path_exists):
        """Test that pool initializes in anonymous mode when no tokens configured."""
        from perplexity.server.client_pool import ClientPool

        # Clear environment variables
        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        assert pool._mode == "anonymous"
        assert len(pool.clients) == 1
        assert "anonymous" in pool.clients

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_initialize_single_mode(self, mock_client_class, mock_path_exists):
        """Test that pool initializes in single mode with env vars."""
        from perplexity.server.client_pool import ClientPool

        env = {
            "PPLX_NEXT_AUTH_CSRF_TOKEN": "test-csrf",
            "PPLX_SESSION_TOKEN": "test-session",
        }
        with patch.dict(os.environ, env, clear=True):
            pool = ClientPool()

        assert pool._mode == "single"
        assert len(pool.clients) == 1
        assert "default" in pool.clients

    @patch("perplexity.server.client_pool.Client")
    def test_initialize_pool_mode_from_config(self, mock_client_class):
        """Test that pool initializes in pool mode from config file."""
        from perplexity.server.client_pool import ClientPool

        config = {
            "tokens": [
                {"id": "user1", "csrf_token": "csrf1", "session_token": "session1"},
                {"id": "user2", "csrf_token": "csrf2", "session_token": "session2"},
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            config_path = f.name

        try:
            pool = ClientPool(config_path)

            assert pool._mode == "pool"
            assert len(pool.clients) == 2
            assert "user1" in pool.clients
            assert "user2" in pool.clients
        finally:
            os.unlink(config_path)

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_add_client(self, mock_client_class, mock_path_exists):
        """Test adding a new client to the pool."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        result = pool.add_client("new-user", "csrf", "session")

        assert result["status"] == "ok"
        assert "new-user" in pool.clients
        assert pool._mode == "pool"  # Mode should change from anonymous to pool

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_add_duplicate_client(self, mock_client_class, mock_path_exists):
        """Test that adding a duplicate client returns an error."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        pool.add_client("user1", "csrf", "session")
        result = pool.add_client("user1", "csrf2", "session2")

        assert result["status"] == "error"
        assert "already exists" in result["message"]

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_remove_client(self, mock_client_class, mock_path_exists):
        """Test removing a client from the pool."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        pool.add_client("user1", "csrf1", "session1")
        pool.add_client("user2", "csrf2", "session2")

        result = pool.remove_client("user1")

        assert result["status"] == "ok"
        assert "user1" not in pool.clients
        assert "user2" in pool.clients

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_remove_last_client_error(self, mock_client_class, mock_path_exists):
        """Test that removing the last client returns an error."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        result = pool.remove_client("anonymous")

        assert result["status"] == "error"
        assert "at least one client must remain" in result["message"].lower()

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_remove_nonexistent_client(self, mock_client_class, mock_path_exists):
        """Test that removing a nonexistent client returns an error."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        result = pool.remove_client("nonexistent")

        assert result["status"] == "error"
        assert "not found" in result["message"]

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_list_clients(self, mock_client_class, mock_path_exists):
        """Test listing all clients."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        pool.add_client("user1", "csrf1", "session1")
        pool.add_client("user2", "csrf2", "session2")

        result = pool.list_clients()

        assert result["status"] == "ok"
        client_ids = [c["id"] for c in result["data"]["clients"]]
        assert "anonymous" in client_ids
        assert "user1" in client_ids
        assert "user2" in client_ids

    @patch("perplexity.server.client_pool.Client")
    @patch("pathlib.Path.exists", return_value=False)
    def test_get_client_round_robin(self, mock_exists, mock_client_class):
        """Test that get_client uses round-robin selection."""
        from perplexity.server.client_pool import ClientPool

        # Mock exists to prevent loading any config file
        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        pool.add_client("user1", "csrf1", "session1")
        pool.add_client("user2", "csrf2", "session2")

        # Get clients multiple times and verify round-robin
        ids = []
        for _ in range(6):
            client_id, client = pool.get_client()
            ids.append(client_id)

        # Should rotate through all clients
        assert "anonymous" in ids
        assert "user1" in ids
        assert "user2" in ids

        # Verify that we see different clients (not all the same)
        unique_ids = set(ids)
        assert len(unique_ids) >= 2, f"Expected round-robin but got: {ids}"

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_get_client_smooth_weighted_round_robin(
        self, mock_client_class, mock_path_exists
    ):
        """Lower-weight healthy clients receive their proportional share."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        pool.add_client("user1", "csrf1", "session1")
        pool.clients["anonymous"].weight = 100
        pool.clients["user1"].weight = 50

        ids = [pool.get_client()[0] for _ in range(6)]

        assert ids == [
            "anonymous",
            "user1",
            "anonymous",
            "anonymous",
            "user1",
            "anonymous",
        ]

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_get_client_skips_unavailable(self, mock_client_class, mock_path_exists):
        """Test that get_client skips clients in backoff."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        pool.add_client("user1", "csrf1", "session1")

        # Mark anonymous client as unavailable
        pool.clients["anonymous"].available_after = time.time() + 1000

        # Should skip anonymous and return user1
        client_id, client = pool.get_client()
        assert client_id == "user1"

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_get_client_skips_explicitly_excluded_clients(
        self, mock_client_class, mock_path_exists
    ):
        """Per-request failover can exclude accounts already attempted."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        pool.add_client("user1", "csrf1", "session1")

        client_id, client = pool.get_client(exclude_ids={"anonymous"})

        assert client_id == "user1"
        assert client is pool.clients["user1"].client

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_get_client_all_unavailable(self, mock_client_class, mock_path_exists):
        """Test get_client when all clients are unavailable."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        # Mark the only client as unavailable
        pool.clients["anonymous"].available_after = time.time() + 1000

        client_id, client = pool.get_client()

        # Should return the client_id but client as None
        assert client_id == "anonymous"
        assert client is None

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_get_client_by_id_never_rotates_or_substitutes(
        self, mock_client_class, mock_path_exists
    ):
        """Session affinity resolves only the requested account."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()
        pool.add_client("user1", "csrf1", "session1")

        scheduler_before = {
            client_id: wrapper.scheduler_current for client_id, wrapper in pool.clients.items()
        }
        client_id, client = pool.get_client_by_id("user1")

        assert client_id == "user1"
        assert client is pool.clients["user1"].client
        assert {
            current_id: wrapper.scheduler_current for current_id, wrapper in pool.clients.items()
        } == scheduler_before

        pool.clients["user1"].available_after = time.time() + 60
        assert pool.get_client_by_id("user1") == ("user1", None)
        assert pool.get_client_by_id("missing") == (None, None)

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_mark_client_success(self, mock_client_class, mock_path_exists):
        """Test marking a client as successful."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        pool.mark_client_success("anonymous")

        assert pool.clients["anonymous"].request_count == 1
        assert pool.clients["anonymous"].fail_count == 0

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_mark_client_failure(self, mock_client_class, mock_path_exists):
        """Test marking a client as failed."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        pool.mark_client_failure("anonymous")

        assert pool.clients["anonymous"].fail_count == 1
        assert pool.clients["anonymous"].is_available() is False

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_get_status(self, mock_client_class, mock_path_exists):
        """Test getting pool status."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        pool.add_client("user1", "csrf1", "session1")

        status = pool.get_status()

        assert status["total"] == 2
        assert status["available"] == 2
        assert status["mode"] == "pool"
        assert len(status["clients"]) == 2

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_get_earliest_available_time(self, mock_client_class, mock_path_exists):
        """Test getting earliest available time when all clients unavailable."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        pool.add_client("user1", "csrf1", "session1")

        # Mark all clients as unavailable with different times
        pool.clients["anonymous"].available_after = time.time() + 100
        pool.clients["user1"].available_after = time.time() + 50

        earliest = pool.get_earliest_available_time()

        assert earliest is not None
        assert "T" in earliest  # ISO8601 format

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_get_earliest_available_time_when_available(self, mock_client_class, mock_path_exists):
        """Test that get_earliest_available_time returns None when client available."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        earliest = pool.get_earliest_available_time()

        assert earliest is None

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_get_client_user_info_releases_pool_lock_before_network(
        self, mock_client_class, mock_path_exists
    ):
        """A slow user-info request must not block other pool operations."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        started = threading.Event()
        release_request = threading.Event()

        def slow_user_info():
            started.set()
            release_request.wait(timeout=2)
            return {"email": "test@example.com"}

        pool.clients["anonymous"].get_user_info = MagicMock(side_effect=slow_user_info)
        thread = threading.Thread(target=pool.get_client_user_info, args=("anonymous",))
        thread.start()
        assert started.wait(timeout=1)

        acquired = False
        try:
            acquired = pool._lock.acquire(timeout=0.2)
            assert acquired, "pool lock was held during the network request"
        finally:
            if acquired:
                pool._lock.release()
            release_request.set()
            thread.join(timeout=2)

        assert not thread.is_alive()

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_get_all_clients_user_info_releases_pool_lock_before_network(
        self, mock_client_class, mock_path_exists
    ):
        """Bulk user-info requests also run from a lock-free snapshot."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        started = threading.Event()
        release_request = threading.Event()

        def slow_user_info():
            started.set()
            release_request.wait(timeout=2)
            return {"email": "test@example.com"}

        pool.clients["anonymous"].get_user_info = MagicMock(side_effect=slow_user_info)
        thread = threading.Thread(target=pool.get_all_clients_user_info)
        thread.start()
        assert started.wait(timeout=1)

        acquired = False
        try:
            acquired = pool._lock.acquire(timeout=0.2)
            assert acquired, "pool lock was held during the network request"
        finally:
            if acquired:
                pool._lock.release()
            release_request.set()
            thread.join(timeout=2)

        assert not thread.is_alive()

    @patch("pathlib.Path.exists", return_value=False)
    @patch("perplexity.server.client_pool.Client")
    def test_thread_safety(self, mock_client_class, mock_path_exists):
        """Test that pool operations are thread-safe."""
        from perplexity.server.client_pool import ClientPool

        with patch.dict(os.environ, {}, clear=True):
            pool = ClientPool()

        errors = []

        def add_clients():
            try:
                for i in range(10):
                    pool.add_client(f"thread-{threading.current_thread().name}-{i}", "csrf", "session")
            except Exception as e:
                errors.append(e)

        def get_clients():
            try:
                for _ in range(20):
                    pool.get_client()
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(3):
            threads.append(threading.Thread(target=add_clients, name=f"add-{i}"))
            threads.append(threading.Thread(target=get_clients, name=f"get-{i}"))

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"


class TestClientPoolConfigValidation:
    """Tests for config file validation."""

    @patch("perplexity.server.client_pool.Client")
    def test_invalid_config_missing_tokens(self, mock_client_class):
        """Test that config without tokens raises an error."""
        from perplexity.server.client_pool import ClientPool

        config = {"tokens": []}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            config_path = f.name

        try:
            with pytest.raises(ValueError, match="No tokens found"):
                ClientPool(config_path)
        finally:
            os.unlink(config_path)

    @patch("perplexity.server.client_pool.Client")
    def test_invalid_config_missing_fields(self, mock_client_class):
        """Test that config with missing fields raises an error."""
        from perplexity.server.client_pool import ClientPool

        config = {
            "tokens": [
                {"id": "user1", "csrf_token": "csrf1"}  # missing session_token
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            config_path = f.name

        try:
            with pytest.raises(ValueError, match="Invalid token entry"):
                ClientPool(config_path)
        finally:
            os.unlink(config_path)
