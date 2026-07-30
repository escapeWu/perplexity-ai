"""Regression tests for public streaming progress normalization."""

from perplexity.server.progress import ProgressTracker


def test_repeated_upstream_stage_updates_one_public_progress_item():
    tracker = ProgressTracker()
    first = tracker.update(
        {
            "text": [
                {
                    "step_type": "SEARCH_RESULTS",
                    "content": {"web_results": [{}] * 15},
                }
            ]
        }
    )
    second = tracker.update(
        {
            "text": [
                {
                    "step_type": "SEARCH_RESULTS",
                    "content": {"web_results": [{}] * 15},
                },
                {
                    "step_type": "SEARCH_RESULTS",
                    "content": {"web_results": [{}] * 2},
                },
            ]
        }
    )

    assert len(first) == 1
    assert len(second) == 1
    assert second[0]["id"] == first[0]["id"]
    assert second[0]["detail"] == {"source_count": 2}
