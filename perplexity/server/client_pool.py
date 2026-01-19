"""
Client pool for managing multiple Perplexity API tokens with load balancing.

Provides round-robin client selection with exponential backoff retry on failures.
Supports heartbeat testing to automatically verify token health.
"""

import asyncio
import json
import logging
import pathlib
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..client import Client

logger = logging.getLogger(__name__)


class ClientWrapper:
    """Wrapper for Client with failure tracking, weight, and availability status."""

    # Weight constants
    DEFAULT_WEIGHT = 100
    MIN_WEIGHT = 10
    WEIGHT_DECAY = 10  # Amount to decrease on pro failure
    WEIGHT_RECOVERY = 5  # Amount to recover on success

    # Backoff constants
    INITIAL_BACKOFF = 60  # First failure: 60 seconds cooldown
    MAX_BACKOFF = 3600  # Maximum backoff: 1 hour

    def __init__(self, client: Client, client_id: str):
        self.client = client
        self.id = client_id
        self.fail_count = 0
        self.available_after: float = 0
        self.request_count = 0
        self.weight = self.DEFAULT_WEIGHT  # Higher weight = higher priority
        self.pro_fail_count = 0  # Track pro-specific failures
        self.enabled = True  # Whether this client is enabled for use
        self.state = "unknown"  # Token state: "normal", "offline", "unknown"
        self.last_heartbeat: Optional[float] = None  # Last heartbeat check timestamp

    def is_available(self) -> bool:
        """Check if the client is currently available (enabled and not in backoff)."""
        return self.enabled and time.time() >= self.available_after

    def mark_failure(self) -> None:
        """Mark the client as failed, applying exponential backoff.

        First failure: 60s cooldown
        Consecutive failures: 60s * 2^(fail_count-1), max 1 hour
        """
        self.fail_count += 1
        # Exponential backoff starting from INITIAL_BACKOFF (60s)
        # 1st fail: 60s, 2nd: 120s, 3rd: 240s, 4th: 480s, ... max: 3600s
        backoff = min(self.MAX_BACKOFF, self.INITIAL_BACKOFF * (2 ** (self.fail_count - 1)))
        self.available_after = time.time() + backoff

    def mark_success(self) -> None:
        """Mark the client as successful, resetting failure state and recovering weight."""
        self.fail_count = 0
        self.available_after = 0
        self.request_count += 1
        # Gradually recover weight on success
        if self.weight < self.DEFAULT_WEIGHT:
            self.weight = min(self.DEFAULT_WEIGHT, self.weight + self.WEIGHT_RECOVERY)

    def mark_pro_failure(self) -> None:
        """Mark that a pro request failed for this client, reducing its weight."""
        self.pro_fail_count += 1
        self.weight = max(self.MIN_WEIGHT, self.weight - self.WEIGHT_DECAY)

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of this client."""
        available = self.is_available()
        next_available_at = None
        if not available:
            next_available_at = datetime.fromtimestamp(
                self.available_after, tz=timezone.utc
            ).isoformat()

        last_heartbeat_at = None
        if self.last_heartbeat:
            last_heartbeat_at = datetime.fromtimestamp(
                self.last_heartbeat, tz=timezone.utc
            ).isoformat()

        return {
            "id": self.id,
            "available": self.is_available(),
            "enabled": self.enabled,
            "state": self.state,
            "fail_count": self.fail_count,
            "next_available_at": next_available_at,
            "last_heartbeat_at": last_heartbeat_at,
            "request_count": self.request_count,
            "weight": self.weight,
            "pro_fail_count": self.pro_fail_count,
        }

    def get_user_info(self) -> Dict[str, Any]:
        """Get user session information for this client."""
        return self.client.get_user_info()


class ClientPool:
    """
    Pool of Client instances with round-robin load balancing.

    Supports dynamic addition and removal of clients at runtime.
    Supports heartbeat testing for automatic token health verification.
    """

    def __init__(self, config_path: Optional[str] = None):
        self.clients: Dict[str, ClientWrapper] = {}
        self._rotation_order: List[str] = []
        self._index = 0
        self._lock = threading.Lock()
        self._mode = "anonymous"

        # Heartbeat configuration
        self._heartbeat_config: Dict[str, Any] = {
            "enable": False,
            "question": "现在是农历几月几号？",
            "interval": 6,  # hours
            "tg_bot_token": None,
            "tg_chat_id": None
        }
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._config_path: Optional[str] = None

        # Load initial clients from config or environment
        self._initialize(config_path)

    def _initialize(self, config_path: Optional[str] = None) -> None:
        """Initialize the pool from config file or environment variables."""
        # Priority 1: Explicit config file path
        if config_path and os.path.exists(config_path):
            self._load_from_config(config_path)
            return

        # Priority 2: Environment variable pointing to config
        env_config_path = os.getenv("PPLX_TOKEN_POOL_CONFIG")
        if env_config_path and os.path.exists(env_config_path):
            self._load_from_config(env_config_path)
            return

        # Priority 3: Default token_pool_config.json in project root
        # Look for config file relative to the module location or current working directory
        default_config_paths = [
            pathlib.Path.cwd() / "token_pool_config.json",  # Current working directory
            pathlib.Path(__file__).parent.parent / "token_pool_config.json",  # Project root
        ]
        for default_path in default_config_paths:
            if default_path.exists():
                self._load_from_config(str(default_path))
                return

        # Priority 4: Single token from environment variables
        csrf_token = os.getenv("PPLX_NEXT_AUTH_CSRF_TOKEN")
        session_token = os.getenv("PPLX_SESSION_TOKEN")
        if csrf_token and session_token:
            self._add_client_internal(
                "default",
                {"next-auth.csrf-token": csrf_token, "__Secure-next-auth.session-token": session_token},
            )
            self._mode = "single"
            return

        # Priority 5: Anonymous client (no cookies)
        self._add_client_internal("anonymous", {})
        self._mode = "anonymous"

    def _load_from_config(self, config_path: str) -> None:
        """Load clients from a JSON configuration file."""
        self._config_path = config_path
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Load heartbeat configuration if present
        heart_beat = config.get("heart_beat")
        if heart_beat and isinstance(heart_beat, dict):
            self._heartbeat_config = {
                "enable": heart_beat.get("enable", False),
                "question": heart_beat.get("question", "现在是农历几月几号？"),
                "interval": heart_beat.get("interval", 6),
                "tg_bot_token": heart_beat.get("tg_bot_token"),
                "tg_chat_id": heart_beat.get("tg_chat_id")
            }

        tokens = config.get("tokens", [])
        if not tokens:
            raise ValueError(f"No tokens found in config file: {config_path}")

        for token_entry in tokens:
            client_id = token_entry.get("id")
            csrf_token = token_entry.get("csrf_token")
            session_token = token_entry.get("session_token")

            if not all([client_id, csrf_token, session_token]):
                raise ValueError(f"Invalid token entry in config: {token_entry}")

            cookies = {
                "next-auth.csrf-token": csrf_token,
                "__Secure-next-auth.session-token": session_token,
            }
            self._add_client_internal(client_id, cookies)

        self._mode = "pool"

    def _add_client_internal(self, client_id: str, cookies: Dict[str, str]) -> None:
        """Internal method to add a client without locking."""
        client = Client(cookies)
        wrapper = ClientWrapper(client, client_id)
        self.clients[client_id] = wrapper
        self._rotation_order.append(client_id)

    def add_client(
        self, client_id: str, csrf_token: str, session_token: str
    ) -> Dict[str, Any]:
        """
        Add a new client to the pool at runtime.

        Returns:
            Dict with status and message
        """
        with self._lock:
            if client_id in self.clients:
                return {
                    "status": "error",
                    "message": f"Client '{client_id}' already exists",
                }

            cookies = {
                "next-auth.csrf-token": csrf_token,
                "__Secure-next-auth.session-token": session_token,
            }
            self._add_client_internal(client_id, cookies)

            # Update mode if transitioning from single/anonymous to pool
            if self._mode in ("single", "anonymous") and len(self.clients) > 1:
                self._mode = "pool"

            return {
                "status": "ok",
                "message": f"Client '{client_id}' added successfully",
            }

    def remove_client(self, client_id: str) -> Dict[str, Any]:
        """
        Remove a client from the pool at runtime.

        Returns:
            Dict with status and message
        """
        with self._lock:
            if client_id not in self.clients:
                return {
                    "status": "error",
                    "message": f"Client '{client_id}' not found",
                }

            if len(self.clients) <= 1:
                return {
                    "status": "error",
                    "message": "Cannot remove the last client. At least one client must remain.",
                }

            del self.clients[client_id]
            self._rotation_order.remove(client_id)

            # Adjust index if needed
            if self._index >= len(self._rotation_order):
                self._index = 0

            return {
                "status": "ok",
                "message": f"Client '{client_id}' removed successfully",
            }

    def list_clients(self) -> Dict[str, Any]:
        """
        List all clients with their id, availability status, and weight.

        Returns:
            Dict with status and client list (sorted by weight descending)
        """
        with self._lock:
            clients = [
                {
                    "id": wrapper.id,
                    "available": wrapper.is_available(),
                    "enabled": wrapper.enabled,
                    "weight": wrapper.weight,
                }
                for wrapper in self.clients.values()
            ]
            # Sort by weight descending
            clients.sort(key=lambda c: c["weight"], reverse=True)
            return {"status": "ok", "data": {"clients": clients}}

    def enable_client(self, client_id: str) -> Dict[str, Any]:
        """
        Enable a client in the pool.

        Returns:
            Dict with status and message
        """
        with self._lock:
            wrapper = self.clients.get(client_id)
            if not wrapper:
                return {"status": "error", "message": f"Client '{client_id}' not found"}
            wrapper.enabled = True
            return {"status": "ok", "message": f"Client '{client_id}' enabled"}

    def disable_client(self, client_id: str) -> Dict[str, Any]:
        """
        Disable a client in the pool.

        Returns:
            Dict with status and message
        """
        with self._lock:
            wrapper = self.clients.get(client_id)
            if not wrapper:
                return {"status": "error", "message": f"Client '{client_id}' not found"}

            # Check if this is the last enabled client
            enabled_count = sum(1 for w in self.clients.values() if w.enabled)
            if enabled_count <= 1 and wrapper.enabled:
                return {
                    "status": "error",
                    "message": "Cannot disable the last enabled client. At least one client must remain enabled.",
                }

            wrapper.enabled = False
            return {"status": "ok", "message": f"Client '{client_id}' disabled"}

    def reset_client(self, client_id: str) -> Dict[str, Any]:
        """
        Reset a client's failure state and weight.

        Returns:
            Dict with status and message
        """
        with self._lock:
            wrapper = self.clients.get(client_id)
            if not wrapper:
                return {"status": "error", "message": f"Client '{client_id}' not found"}
            wrapper.fail_count = 0
            wrapper.pro_fail_count = 0
            wrapper.available_after = 0
            wrapper.weight = ClientWrapper.DEFAULT_WEIGHT
            return {"status": "ok", "message": f"Client '{client_id}' reset successfully"}

    def get_client(self) -> Tuple[Optional[str], Optional[Client]]:
        """
        Get the next available client using weighted round-robin selection.

        When clients have equal weights, they are selected in round-robin order.
        When weights differ, higher weight clients are selected more frequently.

        Returns:
            Tuple of (client_id, Client) or (None, None) if no clients available
        """
        with self._lock:
            if not self.clients:
                return None, None

            # Get available clients in rotation order
            available_wrappers = [
                self.clients[client_id]
                for client_id in self._rotation_order
                if self.clients[client_id].is_available()
            ]

            if available_wrappers:
                # Find the max weight among available clients
                max_weight = max(w.weight for w in available_wrappers)

                # Get clients with the highest weight (for weighted selection)
                top_weight_clients = [w for w in available_wrappers if w.weight == max_weight]

                if len(top_weight_clients) == 1:
                    # Only one client with highest weight, use it
                    return top_weight_clients[0].id, top_weight_clients[0].client

                # Multiple clients with same weight - use round-robin among them
                # Find the next client in rotation order that's in our top weight list
                top_weight_ids = {w.id for w in top_weight_clients}
                start_index = self._index

                for _ in range(len(self._rotation_order)):
                    client_id = self._rotation_order[self._index]
                    self._index = (self._index + 1) % len(self._rotation_order)

                    if client_id in top_weight_ids:
                        return client_id, self.clients[client_id].client

                # Fallback (shouldn't happen): return first top weight client
                return top_weight_clients[0].id, top_weight_clients[0].client

            # No available clients - return the one that will be available soonest
            soonest_wrapper = min(
                self.clients.values(), key=lambda w: w.available_after
            )
            return soonest_wrapper.id, None

    def mark_client_success(self, client_id: str) -> None:
        """Mark a client as successful after a request."""
        with self._lock:
            wrapper = self.clients.get(client_id)
            if wrapper:
                wrapper.mark_success()

    def mark_client_failure(self, client_id: str) -> None:
        """Mark a client as failed after a request."""
        with self._lock:
            wrapper = self.clients.get(client_id)
            if wrapper:
                wrapper.mark_failure()

    def mark_client_pro_failure(self, client_id: str) -> None:
        """Mark a client as failed for pro request, reducing its weight."""
        with self._lock:
            wrapper = self.clients.get(client_id)
            if wrapper:
                wrapper.mark_pro_failure()

    def get_status(self) -> Dict[str, Any]:
        """
        Get detailed status of the entire pool.

        Returns:
            Dict with total, available, mode, and client details
        """
        with self._lock:
            clients_status = [
                wrapper.get_status() for wrapper in self.clients.values()
            ]
            available_count = sum(
                1 for wrapper in self.clients.values() if wrapper.is_available()
            )

            return {
                "total": len(self.clients),
                "available": available_count,
                "mode": self._mode,
                "clients": clients_status,
            }

    def get_earliest_available_time(self) -> Optional[str]:
        """Get the earliest time any client will become available."""
        with self._lock:
            if not self.clients:
                return None

            # Check if any client is currently available
            for wrapper in self.clients.values():
                if wrapper.is_available():
                    return None

            # Find the earliest available time
            earliest = min(self.clients.values(), key=lambda w: w.available_after)
            return datetime.fromtimestamp(
                earliest.available_after, tz=timezone.utc
            ).isoformat()

    def get_client_user_info(self, client_id: str) -> Dict[str, Any]:
        """
        Get user session information for a specific client.

        Returns:
            Dict with user info or error message
        """
        with self._lock:
            wrapper = self.clients.get(client_id)
            if not wrapper:
                return {"status": "error", "message": f"Client '{client_id}' not found"}
            return {"status": "ok", "data": wrapper.get_user_info()}

    def get_all_clients_user_info(self) -> Dict[str, Any]:
        """
        Get user session information for all clients.

        Returns:
            Dict with client_id -> user_info mapping
        """
        with self._lock:
            result = {}
            for client_id, wrapper in self.clients.items():
                result[client_id] = wrapper.get_user_info()
            return {"status": "ok", "data": result}

    # ==================== Heartbeat Methods ====================

    def get_heartbeat_config(self) -> Dict[str, Any]:
        """Get the current heartbeat configuration."""
        return self._heartbeat_config.copy()

    def update_heartbeat_config(self, new_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update heartbeat configuration and save to config file.

        Args:
            new_config: Dict with configuration fields to update

        Returns:
            Dict with status and updated config
        """
        # Update in-memory config
        for key in ["enable", "question", "interval", "tg_bot_token", "tg_chat_id"]:
            if key in new_config:
                self._heartbeat_config[key] = new_config[key]

        # Save to config file if available
        if self._config_path and os.path.exists(self._config_path):
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

                # Update heart_beat section
                config["heart_beat"] = {
                    "enable": self._heartbeat_config["enable"],
                    "question": self._heartbeat_config["question"],
                    "interval": self._heartbeat_config["interval"],
                    "tg_bot_token": self._heartbeat_config["tg_bot_token"],
                    "tg_chat_id": self._heartbeat_config["tg_chat_id"]
                }

                with open(self._config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)

                logger.info(f"Heartbeat config saved to {self._config_path}")
            except Exception as e:
                logger.error(f"Failed to save heartbeat config: {e}")
                return {"status": "error", "message": f"Failed to save config: {e}"}

        return {"status": "ok", "config": self._heartbeat_config.copy()}

    def is_heartbeat_enabled(self) -> bool:
        """Check if heartbeat is enabled."""
        return self._heartbeat_config.get("enable", False)

    async def _send_telegram_notification(self, message: str) -> None:
        """Send a notification to Telegram."""
        bot_token = self._heartbeat_config.get("tg_bot_token")
        chat_id = self._heartbeat_config.get("tg_chat_id")

        if not bot_token or not chat_id:
            logger.warning("Telegram notification skipped: tg_bot_token or tg_chat_id not configured")
            return

        try:
            import aiohttp
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        logger.error(f"Failed to send Telegram notification: {await resp.text()}")
                    else:
                        logger.info(f"Telegram notification sent: {message}")
        except ImportError:
            logger.warning("aiohttp not installed, Telegram notification skipped")
        except Exception as e:
            logger.error(f"Error sending Telegram notification: {e}")

    async def test_client(self, client_id: str) -> Dict[str, Any]:
        """
        Test a single client by performing a query.

        Returns:
            Dict with status and result
        """
        with self._lock:
            wrapper = self.clients.get(client_id)
            if not wrapper:
                return {"status": "error", "message": f"Client '{client_id}' not found"}
            client = wrapper.client

        question = self._heartbeat_config.get("question", "现在是农历几月几号？")
        prev_state = wrapper.state

        try:
            # Perform a simple search query
            response = await asyncio.to_thread(
                client.search,
                question,
                mode="auto",
                model=None,
                sources=["web"],
                files={},
                stream=False,
                language="zh-CN",
                incognito=True,
            )

            # Check if response contains answer
            if response and "answer" in response:
                with self._lock:
                    wrapper.state = "normal"
                    wrapper.last_heartbeat = time.time()
                logger.info(f"Heartbeat test passed for client '{client_id}'")
                return {"status": "ok", "state": "normal", "client_id": client_id}
            else:
                with self._lock:
                    wrapper.state = "offline"
                    wrapper.last_heartbeat = time.time()
                logger.warning(f"Heartbeat test failed for client '{client_id}': no answer in response")

                # Send Telegram notification if state changed to offline
                if prev_state != "offline":
                    await self._send_telegram_notification(
                        f"⚠️ perplexity mcp: <b>{client_id}</b> test failed."
                    )

                return {"status": "error", "state": "offline", "client_id": client_id}

        except Exception as e:
            with self._lock:
                wrapper.state = "offline"
                wrapper.last_heartbeat = time.time()
            logger.error(f"Heartbeat test failed for client '{client_id}': {e}")

            # Send Telegram notification if state changed to offline
            if prev_state != "offline":
                await self._send_telegram_notification(
                    f"⚠️ perplexity mcp: <b>{client_id}</b> test failed."
                )

            return {"status": "error", "state": "offline", "client_id": client_id, "error": str(e)}

    async def test_all_clients(self) -> Dict[str, Any]:
        """
        Test all clients in the pool with concurrent execution.

        Uses asyncio.Semaphore to limit concurrency to 5 simultaneous tests
        to prevent rate limiting while improving overall test performance.

        Returns:
            Dict with status and results for each client
        """
        results: Dict[str, Any] = {}
        client_ids = list(self.clients.keys())

        if not client_ids:
            logger.info("No clients to test")
            return {"status": "ok", "results": results}

        logger.info(f"Starting concurrent test for {len(client_ids)} clients (max concurrency: 5)")

        # Limit concurrent tests to 5 to prevent rate limiting
        semaphore = asyncio.Semaphore(5)
        completed_count = 0

        async def test_with_limit(client_id: str) -> Tuple[str, Dict[str, Any]]:
            nonlocal completed_count
            logger.info(f"Testing client '{client_id}'...")
            async with semaphore:
                result = await self.test_client(client_id)
                completed_count += 1
                status = result.get("status", "unknown")
                state = result.get("state", "unknown")
                logger.info(
                    f"Client '{client_id}' test completed ({completed_count}/{len(client_ids)}): "
                    f"status={status}, state={state}"
                )
                # Small delay after each test to prevent burst requests
                await asyncio.sleep(0.5)
                return client_id, result

        # Run all tests concurrently (semaphore limits to 5 at a time)
        tasks = [test_with_limit(cid) for cid in client_ids]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for item in completed:
            if isinstance(item, Exception):
                # Log unexpected errors but continue processing
                logger.error(f"Unexpected error during concurrent test: {item}")
                continue
            client_id, result = item
            results[client_id] = result

        # Summary log
        success_count = sum(1 for r in results.values() if r.get("status") == "ok")
        fail_count = len(results) - success_count
        logger.info(
            f"Concurrent test completed: {len(results)} clients tested, "
            f"{success_count} succeeded, {fail_count} failed"
        )

        return {"status": "ok", "results": results}

    async def _heartbeat_loop(self) -> None:
        """Background task that periodically tests all clients."""
        interval_hours = self._heartbeat_config.get("interval", 6)
        interval_seconds = interval_hours * 3600

        logger.info(f"Heartbeat loop started, interval: {interval_hours} hours")

        while True:
            try:
                # Test all clients
                logger.info("Starting heartbeat test for all clients...")
                await self.test_all_clients()
                logger.info("Heartbeat test completed")
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")

            # Wait for next interval
            await asyncio.sleep(interval_seconds)

    def start_heartbeat(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> bool:
        """
        Start the heartbeat background task.

        Args:
            loop: Optional event loop to use. If not provided, will try to get the running loop.

        Returns:
            True if heartbeat was started, False if disabled or already running
        """
        if not self.is_heartbeat_enabled():
            logger.info("Heartbeat is disabled, not starting")
            return False

        if self._heartbeat_task and not self._heartbeat_task.done():
            logger.info("Heartbeat task already running")
            return False

        try:
            if loop is None:
                loop = asyncio.get_running_loop()
            self._heartbeat_task = loop.create_task(self._heartbeat_loop())
            logger.info("Heartbeat task started")
            return True
        except RuntimeError:
            logger.warning("No running event loop, heartbeat not started")
            return False

    def stop_heartbeat(self) -> bool:
        """
        Stop the heartbeat background task.

        Returns:
            True if heartbeat was stopped, False if not running
        """
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            logger.info("Heartbeat task stopped")
            return True
        return False
