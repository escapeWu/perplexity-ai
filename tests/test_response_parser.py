"""Tests for the evolving upstream block response protocol."""

from perplexity.response_parser import UpstreamResponseAccumulator


def workflow_stages(response):
    return [step["step_type"] for step in response["text"]]


def test_block_responses_restore_cumulative_answer_sources_and_workflow():
    accumulator = UpstreamResponseAccumulator()

    initial = accumulator.normalize({"blocks": []})
    sources = accumulator.normalize(
        {
            "blocks": [
                {
                    "intended_usage": "web_results",
                    "web_result_block": {
                        "progress": "IN_PROGRESS",
                        "web_results": [{"url": "https://example.com", "name": "Example"}],
                    },
                }
            ]
        }
    )
    first_answer = accumulator.normalize(
        {
            "blocks": [
                {
                    "intended_usage": "ask_text",
                    "markdown_block": {
                        "progress": "IN_PROGRESS",
                        "chunks": ["Hel", "l"],
                        "chunk_starting_offset": 0,
                    },
                }
            ]
        }
    )
    appended_answer = accumulator.normalize(
        {
            "blocks": [
                {
                    "intended_usage": "ask_text",
                    "markdown_block": {
                        "progress": "IN_PROGRESS",
                        "chunks": ["o"],
                        "chunk_starting_offset": 2,
                    },
                }
            ]
        }
    )

    assert workflow_stages(initial) == ["INITIAL_QUERY"]
    assert workflow_stages(sources) == [
        "INITIAL_QUERY",
        "SEARCH_WEB",
        "SEARCH_RESULTS",
    ]
    assert sources["chunks"] == [{"url": "https://example.com", "name": "Example"}]
    assert workflow_stages(first_answer) == [
        "INITIAL_QUERY",
        "SEARCH_WEB",
        "SEARCH_RESULTS",
        "FINAL",
    ]
    assert first_answer["answer"] == "Hell"
    assert appended_answer["answer"] == "Hello"


def test_explicit_final_answer_wins_over_intermediate_chunks():
    accumulator = UpstreamResponseAccumulator()
    accumulator.normalize(
        {
            "blocks": [
                {
                    "markdown_block": {
                        "chunks": ["partial"],
                        "chunk_starting_offset": 0,
                    }
                }
            ]
        }
    )

    final = accumulator.normalize(
        {
            "blocks": [
                {
                    "markdown_block": {
                        "progress": "DONE",
                        "chunks": ["complete"],
                        "chunk_starting_offset": 0,
                        "answer": "authoritative final answer",
                    }
                }
            ]
        }
    )

    assert final["answer"] == "authoritative final answer"


def test_non_block_response_is_unchanged():
    accumulator = UpstreamResponseAccumulator()
    response = {"answer": "legacy", "text": [{"step_type": "FINAL", "content": {}}]}

    assert accumulator.normalize(response) is response
    assert response["answer"] == "legacy"
