"""Account subscription-tier discovery and pool routing tests."""

import json
from unittest.mock import MagicMock, patch

import pytest
from starlette.requests import Request

from perplexity.client import Client
from perplexity.model_registry import ModelDefinition, ModelRegistry
from perplexity.server import oai
from perplexity.server.client_pool import ClientPool, ClientWrapper


def make_pool_with_tiers() -> ClientPool:
    with (
        patch("pathlib.Path.exists", return_value=False),
        patch("perplexity.server.client_pool.Client"),
        patch.dict("os.environ", {}, clear=True),
    ):
        pool = ClientPool()

    clients = {}
    order = []
    for client_id, tier, own in [
        ("anonymous", "free", False),
        ("pro-account", "pro", True),
        ("max-account", "max", True),
    ]:
        client = MagicMock()
        client.own = own
        wrapper = ClientWrapper(client, client_id)
        wrapper.subscription_tier = tier
        clients[client_id] = wrapper
        order.append(client_id)
    pool.clients = clients
    pool._rotation_order = order
    return pool


def test_max_requests_are_routed_only_to_max_accounts() -> None:
    pool = make_pool_with_tiers()

    selected = [pool.get_client(required_tier="max")[0] for _ in range(3)]

    assert selected == ["max-account", "max-account", "max-account"]


def test_pro_requests_can_use_pro_and_max_but_not_anonymous() -> None:
    pool = make_pool_with_tiers()

    selected = {pool.get_client(required_tier="pro")[0] for _ in range(4)}

    assert selected == {"pro-account", "max-account"}
    assert "anonymous" not in selected


def test_pool_reports_model_tiers_from_enabled_accounts() -> None:
    pool = make_pool_with_tiers()
    assert pool.get_model_subscription_tiers() == {"pro", "max"}

    pool.clients["max-account"].enabled = False
    assert pool.get_model_subscription_tiers() == {"pro"}


def test_client_reads_and_refreshes_subscription_tier() -> None:
    session = MagicMock()
    initial_response = MagicMock()
    initial_response.ok = True
    initial_response.json.return_value = {"user": {"subscription_tier": "max"}}
    refreshed_response = MagicMock()
    refreshed_response.ok = True
    refreshed_response.json.return_value = {"user": {"subscription_tier": "pro"}}
    session.get.side_effect = [initial_response, refreshed_response]

    with patch("perplexity.client.requests.Session", return_value=session):
        client = Client({"__Secure-next-auth.session-token": "test"})

    assert client.subscription_tier == "max"
    assert client.get_user_info()["user"]["subscription_tier"] == "pro"
    assert client.subscription_tier == "pro"


def test_unknown_account_tier_cannot_select_max_model(tmp_path) -> None:
    registry = ModelRegistry(cache_path=tmp_path / "models.json")
    registry._definitions.append(
        ModelDefinition(
            mode="pro",
            public_name="gpt-5.6-sol",
            internal_id="gpt56_sol",
            subscription_tier="max",
            label="GPT-5.6 Sol",
        )
    )
    with pytest.raises(ValueError, match="requires a max account"):
        registry.resolve("pro", "gpt-5.6-sol", account_tier="unknown")


def registry_with_max_model(tmp_path) -> ModelRegistry:
    registry = ModelRegistry(cache_path=tmp_path / "models.json")
    registry._definitions.append(
        ModelDefinition(
            mode="pro",
            public_name="gpt-5.6-sol",
            internal_id="gpt56_sol",
            subscription_tier="max",
            label="GPT-5.6 Sol",
        )
    )
    return registry


def authenticated_request(method: str = "GET", payload: dict | None = None) -> Request:
    body = json.dumps(payload or {}).encode()
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/v1/models" if method == "GET" else "/v1/chat/completions",
            "headers": [(b"authorization", f"Bearer {oai.MCP_TOKEN}".encode())],
        },
        receive,
    )


@pytest.mark.asyncio
async def test_oai_model_list_uses_configured_account_tiers(tmp_path, monkeypatch) -> None:
    registry = registry_with_max_model(tmp_path)
    monkeypatch.setattr("perplexity.model_registry._registry", registry)
    pool = MagicMock()

    pool.get_model_subscription_tiers.return_value = {"pro"}
    with patch("perplexity.server.oai.get_pool", return_value=pool):
        pro_response = await oai.oai_list_models(authenticated_request())
    pro_ids = {model["id"] for model in json.loads(pro_response.body)["data"]}
    assert "gpt-5-6-sol" not in pro_ids

    pool.get_model_subscription_tiers.return_value = {"max"}
    with patch("perplexity.server.oai.get_pool", return_value=pool):
        max_response = await oai.oai_list_models(authenticated_request())
    max_ids = {model["id"] for model in json.loads(max_response.body)["data"]}
    assert "gpt-5-6-sol" in max_ids


@pytest.mark.asyncio
async def test_oai_rejects_max_model_for_pro_only_pool(tmp_path, monkeypatch) -> None:
    registry = registry_with_max_model(tmp_path)
    monkeypatch.setattr("perplexity.model_registry._registry", registry)
    pool = MagicMock()
    pool.get_model_subscription_tiers.return_value = {"pro"}

    with patch("perplexity.server.oai.get_pool", return_value=pool):
        response = await oai.oai_chat_completions(
            authenticated_request(
                "POST",
                {
                    "model": "gpt-5-6-sol",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
        )

    assert response.status_code == 400
    assert "unavailable" in json.loads(response.body)["error"]["message"]
