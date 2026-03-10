"""OpenAI-compatible API 端点测试。

测试覆盖：
1. /v1/models - 模型列表
2. /v1/chat/completions - 聊天补全（非流式）
3. /v1/chat/completions - 聊天补全（流式）
4. 认证验证

使用 httpx 直接调用 HTTP 端点。
"""

import os
import pytest
import httpx
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

# 加载 .env 文件
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# OAI API 配置
OAI_BASE_URL = "http://127.0.0.1:8000"
MCP_TOKEN = os.getenv("MCP_TOKEN", "sk-123456")

# 超时配置（秒）
REQUEST_TIMEOUT = 60

# 测试问题
TEST_QUESTION = "2026农历新年多少号，有什么习俗"

# 测试模型列表
TEST_MODELS = ["perplexity-search", "perplexity-deepsearch", "perplexity-thinking"]


def get_auth_headers(token: str = MCP_TOKEN) -> Dict[str, str]:
    """获取认证 headers。"""
    return {"Authorization": f"Bearer {token}"}


class TestOAIAuthentication:
    """OAI API 认证测试。"""

    def test_models_without_auth_rejected(self) -> None:
        """测试无认证请求被拒绝。"""
        print("console.log -> 测试无认证访问 /v1/models")
        response = httpx.get(
            f"{OAI_BASE_URL}/v1/models",
            timeout=REQUEST_TIMEOUT
        )
        assert response.status_code == 401
        data = response.json()
        assert "error" in data
        print(f"console.log -> 无认证请求被正确拒绝: {data['error']['message']}")

    def test_models_with_invalid_token_rejected(self) -> None:
        """测试无效 token 被拒绝。"""
        print("console.log -> 测试无效 token 访问 /v1/models")
        response = httpx.get(
            f"{OAI_BASE_URL}/v1/models",
            headers=get_auth_headers("invalid-token"),
            timeout=REQUEST_TIMEOUT
        )
        assert response.status_code == 401
        data = response.json()
        assert "error" in data
        print(f"console.log -> 无效 token 被正确拒绝: {data['error']['message']}")

    def test_models_with_valid_token_accepted(self) -> None:
        """测试有效 token 被接受。"""
        print("console.log -> 测试有效 token 访问 /v1/models")
        response = httpx.get(
            f"{OAI_BASE_URL}/v1/models",
            headers=get_auth_headers(),
            timeout=REQUEST_TIMEOUT
        )
        assert response.status_code == 200
        print("console.log -> 有效 token 认证成功")


class TestOAIModels:
    """OAI 模型列表测试。"""

    def test_list_models_structure(self) -> None:
        """测试 /v1/models 返回正确的数据结构。"""
        print("console.log -> 测试 /v1/models 端点")
        response = httpx.get(
            f"{OAI_BASE_URL}/v1/models",
            headers=get_auth_headers(),
            timeout=REQUEST_TIMEOUT
        )
        assert response.status_code == 200
        data = response.json()

        # 验证 OpenAI 格式
        assert data["object"] == "list"
        assert "data" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) > 0

        print(f"console.log -> 返回 {len(data['data'])} 个模型")

        # 验证模型结构
        for model in data["data"]:
            assert "id" in model
            assert "object" in model
            assert model["object"] == "model"
            assert "created" in model
            assert "owned_by" in model
            print(f"console.log -> 模型: {model['id']}")

    def test_list_models_contains_expected_models(self) -> None:
        """测试模型列表包含预期的模型。"""
        print("console.log -> 验证预期模型存在")
        response = httpx.get(
            f"{OAI_BASE_URL}/v1/models",
            headers=get_auth_headers(),
            timeout=REQUEST_TIMEOUT
        )
        data = response.json()
        model_ids = [m["id"] for m in data["data"]]

        # 验证一些预期的模型存在
        expected_models = [
            "perplexity-search",
            "perplexity-thinking",
            "perplexity-deepsearch",
            "gpt-5-4",
            "gpt-5-4-thinking",
        ]
        for model_id in expected_models:
            assert model_id in model_ids, f"没有找到预期模型 '{model_id}'"
            print(f"console.log -> 找到模型: {model_id}")

        unexpected_models = [
            "gpt-5-2",
            "gpt-5-2-thinking",
            "grok-4-1",
            "grok-4-1-thinking",
        ]
        for model_id in unexpected_models:
            assert model_id not in model_ids, f"不应再暴露旧模型 '{model_id}'"
            print(f"console.log -> 已确认旧模型不存在: {model_id}")


class TestOAIChatCompletions:
    """OAI 聊天补全测试。"""

    def test_chat_completions_missing_model_error(self) -> None:
        """测试缺少 model 参数返回错误。"""
        print("console.log -> 测试缺少 model 参数")
        response = httpx.post(
            f"{OAI_BASE_URL}/v1/chat/completions",
            headers=get_auth_headers(),
            json={"messages": [{"role": "user", "content": "Hello"}]},
            timeout=REQUEST_TIMEOUT
        )
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        print(f"console.log -> 正确返回错误: {data['error']['message']}")

    def test_chat_completions_missing_messages_error(self) -> None:
        """测试缺少 messages 参数返回错误。"""
        print("console.log -> 测试缺少 messages 参数")
        response = httpx.post(
            f"{OAI_BASE_URL}/v1/chat/completions",
            headers=get_auth_headers(),
            json={"model": "perplexity-search"},
            timeout=REQUEST_TIMEOUT
        )
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        print(f"console.log -> 正确返回错误: {data['error']['message']}")

    def test_chat_completions_invalid_model_error(self) -> None:
        """测试无效模型名返回错误。"""
        print("console.log -> 测试无效模型名")
        response = httpx.post(
            f"{OAI_BASE_URL}/v1/chat/completions",
            headers=get_auth_headers(),
            json={
                "model": "invalid-model-name",
                "messages": [{"role": "user", "content": "Hello"}]
            },
            timeout=REQUEST_TIMEOUT
        )
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "Unknown model" in data["error"]["message"]
        print(f"console.log -> 正确返回错误: {data['error']['message']}")

    def test_chat_completions_non_stream(self) -> None:
        """测试非流式聊天补全。"""
        print("console.log -> 测试非流式聊天补全")
        response = httpx.post(
            f"{OAI_BASE_URL}/v1/chat/completions",
            headers=get_auth_headers(),
            json={
                "model": "perplexity-search",
                "messages": [{"role": "user", "content": TEST_QUESTION}],
                "stream": False
            },
            timeout=REQUEST_TIMEOUT
        )
        assert response.status_code == 200
        data = response.json()

        # 验证 OpenAI 格式
        assert "id" in data
        assert data["object"] == "chat.completion"
        assert "created" in data
        assert "model" in data
        assert "choices" in data
        assert len(data["choices"]) > 0

        # 验证 choice 结构
        choice = data["choices"][0]
        assert choice["index"] == 0
        assert "message" in choice
        assert choice["message"]["role"] == "assistant"
        assert "content" in choice["message"]
        assert choice["finish_reason"] == "stop"

        # 验证 usage
        assert "usage" in data
        assert "prompt_tokens" in data["usage"]
        assert "completion_tokens" in data["usage"]
        assert "total_tokens" in data["usage"]

        answer = choice["message"]["content"]
        print(f"console.log -> 非流式补全成功")
        print(f"console.log -> 回答预览: {answer[:200]}..." if len(answer) > 200 else f"console.log -> 回答: {answer}")

    def test_chat_completions_stream(self) -> None:
        """测试流式聊天补全。"""
        print("console.log -> 测试流式聊天补全")

        with httpx.stream(
            "POST",
            f"{OAI_BASE_URL}/v1/chat/completions",
            headers=get_auth_headers(),
            json={
                "model": "perplexity-search",
                "messages": [{"role": "user", "content": TEST_QUESTION}],
                "stream": True
            },
            timeout=REQUEST_TIMEOUT
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

            chunks_received = 0
            content_chunks = []
            done_received = False

            for line in response.iter_lines():
                if not line:
                    continue

                if line == "data: [DONE]":
                    done_received = True
                    break

                if line.startswith("data: "):
                    import json
                    chunk_data = json.loads(line[6:])
                    chunks_received += 1

                    # 验证 chunk 结构
                    assert "id" in chunk_data
                    assert chunk_data["object"] == "chat.completion.chunk"
                    assert "choices" in chunk_data

                    if chunk_data["choices"]:
                        delta = chunk_data["choices"][0].get("delta", {})
                        if "content" in delta:
                            content_chunks.append(delta["content"])

            assert done_received, "未收到 [DONE] 标记"
            assert chunks_received > 0, "未收到任何 chunk"

            full_content = "".join(content_chunks)
            print(f"console.log -> 流式补全成功，收到 {chunks_received} 个 chunks")
            print(f"console.log -> 完整回答预览: {full_content[:200]}..." if len(full_content) > 200 else f"console.log -> 完整回答: {full_content}")


class TestOAIChatCompletionsWithArrayContent:
    """测试 messages 中 content 为数组格式的情况。"""

    def test_chat_completions_with_array_content(self) -> None:
        """测试 content 为数组格式。"""
        print("console.log -> 测试 content 数组格式")
        response = httpx.post(
            f"{OAI_BASE_URL}/v1/chat/completions",
            headers=get_auth_headers(),
            json={
                "model": "perplexity-search",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is"},
                        {"type": "text", "text": " the capital of France?"}
                    ]
                }],
                "stream": False
            },
            timeout=REQUEST_TIMEOUT
        )
        assert response.status_code == 200
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        print(f"console.log -> 数组格式 content 解析成功")


class TestOAIMultipleModels:
    """测试多个模型（search, research, reasoning）。"""

    @pytest.mark.parametrize("model", TEST_MODELS)
    def test_chat_completions_non_stream_multiple_models(self, model: str) -> None:
        """测试多个模型的非流式聊天补全。"""
        print(f"console.log -> 测试模型 {model} 非流式补全")
        response = httpx.post(
            f"{OAI_BASE_URL}/v1/chat/completions",
            headers=get_auth_headers(),
            json={
                "model": model,
                "messages": [{"role": "user", "content": TEST_QUESTION}],
                "stream": False
            },
            timeout=REQUEST_TIMEOUT * 3  # research/reasoning 可能需要更长时间
        )
        assert response.status_code == 200, f"模型 {model} 请求失败: {response.text}"
        data = response.json()

        # 验证 OpenAI 格式
        assert "id" in data
        assert data["object"] == "chat.completion"
        assert "choices" in data
        assert len(data["choices"]) > 0

        # 验证回答内容
        answer = data["choices"][0]["message"]["content"]
        assert len(answer) > 0, f"模型 {model} 返回空回答"
        print(f"console.log -> 模型 {model} 非流式补全成功")
        print(f"console.log -> 回答预览: {answer[:300]}..." if len(answer) > 300 else f"console.log -> 回答: {answer}")

    @pytest.mark.parametrize("model", TEST_MODELS)
    def test_chat_completions_stream_multiple_models(self, model: str) -> None:
        """测试多个模型的流式聊天补全。"""
        print(f"console.log -> 测试模型 {model} 流式补全")

        with httpx.stream(
            "POST",
            f"{OAI_BASE_URL}/v1/chat/completions",
            headers=get_auth_headers(),
            json={
                "model": model,
                "messages": [{"role": "user", "content": TEST_QUESTION}],
                "stream": True
            },
            timeout=REQUEST_TIMEOUT * 3
        ) as response:
            assert response.status_code == 200, f"模型 {model} 请求失败"
            assert "text/event-stream" in response.headers.get("content-type", "")

            chunks_received = 0
            content_chunks = []
            done_received = False

            for line in response.iter_lines():
                if not line:
                    continue

                if line == "data: [DONE]":
                    done_received = True
                    break

                if line.startswith("data: "):
                    import json
                    chunk_data = json.loads(line[6:])
                    chunks_received += 1

                    assert "id" in chunk_data
                    assert chunk_data["object"] == "chat.completion.chunk"

                    if chunk_data["choices"]:
                        delta = chunk_data["choices"][0].get("delta", {})
                        if "content" in delta:
                            content_chunks.append(delta["content"])

            assert done_received, f"模型 {model} 未收到 [DONE] 标记"
            assert chunks_received > 0, f"模型 {model} 未收到任何 chunk"

            full_content = "".join(content_chunks)
            print(f"console.log -> 模型 {model} 流式补全成功，收到 {chunks_received} 个 chunks")
            print(f"console.log -> 完整回答预览: {full_content[:300]}..." if len(full_content) > 300 else f"console.log -> 完整回答: {full_content}")
